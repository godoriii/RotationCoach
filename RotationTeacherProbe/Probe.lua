-- Rotation Teacher Probe (M0)
-- Purpose: find out what an addon can actually read about the player's own rotation in
-- Midnight 12.1.x, in each kind of content. It only records; it shows nothing in combat.
-- Output: RotationTeacherProbeDB (SavedVariables), written on /reload or logout.
--
-- Rule used everywhere in this file: a value returned by a game API is never compared,
-- indexed or used in arithmetic until it has gone through plain(), because doing that
-- with a secret value raises a Lua error.

local ADDON_NAME = ...
local PROBE_VERSION = 1
local MAX_SESSIONS = 30
local MAX_EVENTS = 6000
local MAX_WATCH = 40
local PREPULL_SECONDS = 10
local SECRET = "<secret>"

local DB
local session            -- active session or nil
local prebuf = {}        -- recent out-of-combat events, to capture pre-pull casts
local watch = {}         -- spellID -> true, spells the player has cast (cooldown snapshot targets)
local watchCount = 0
local enabled = true

---------------------------------------------------------------------------
-- Secret-safe helpers
---------------------------------------------------------------------------

local issecretErrors = 0

local function isSecret(v)
    if type(issecretvalue) ~= "function" then return false end
    local ok, res = pcall(issecretvalue, v)
    if not ok then
        issecretErrors = issecretErrors + 1
        return true
    end
    return res and true or false
end

-- Turn any API value into something safe to store and compare.
local function plain(v)
    local t = type(v)
    if t == "nil" then return nil end
    if isSecret(v) then return SECRET end
    if t == "number" or t == "string" or t == "boolean" then return v end
    return "<" .. t .. ">"
end

-- A table we may index: a real table that is not itself a secret.
local function isTable(v)
    return type(v) == "table" and not isSecret(v)
end

local function round(n, digits)
    local m = 10 ^ (digits or 3)
    return math.floor(n * m + 0.5) / m
end

local function num(v, digits)
    local p = plain(v)
    if type(p) == "number" then return round(p, digits or 2) end
    return p
end

-- Call an API that may not exist or may throw; returns plain results or nil, err.
local function try(fn, ...)
    if type(fn) ~= "function" then return nil, "missing" end
    local ok, a, b, c = pcall(fn, ...)
    if not ok then return nil, tostring(a) end
    return a, b, c
end

local function logError(where, err)
    local list = session and session.errors or DB.errors
    if #list < 30 then
        list[#list + 1] = where .. ": " .. tostring(err)
    end
end

-- Run a recorder step; an unexpected error must never break the next step.
local function guarded(where, fn, ...)
    local ok, err = pcall(fn, ...)
    if not ok then logError(where, err) end
end

---------------------------------------------------------------------------
-- Snapshots
---------------------------------------------------------------------------

-- One spell's readable cooldown/usability state, as a compact token string.
local function spellState(spellID)
    local tokens = {}
    local function add(s) tokens[#tokens + 1] = s end

    local cd, cdErr = try(C_Spell and C_Spell.GetSpellCooldown, spellID)
    if isTable(cd) then
        local active = plain(cd.isActive)
        if active == true then add("cd") elseif active == SECRET then add("cd=?") end
        if plain(cd.isOnGCD) == true then add("gcd") end
        local dur, start = plain(cd.duration), plain(cd.startTime)
        if dur == SECRET or start == SECRET then
            add("dur=?")
        elseif type(dur) == "number" and dur > 0 and type(start) == "number" then
            add("dur=" .. round(dur, 2))
            add("rem=" .. round(start + dur - GetTime(), 2))
        end
    elseif cdErr and cdErr ~= "missing" then
        add("cderr")
    end

    local ch = try(C_Spell and C_Spell.GetSpellCharges, spellID)
    if isTable(ch) then
        local maxC = plain(ch.maxCharges)
        if type(maxC) == "number" and maxC > 1 then
            local cur = plain(ch.currentCharges)
            add("ch=" .. (cur == SECRET and "?" or tostring(cur)) .. "/" .. maxC)
            local rech = plain(ch.isActive)
            if rech == true then add("rech") elseif rech == SECRET then add("rech=?") end
        end
    end

    local usable, noPower = try(C_Spell and C_Spell.IsSpellUsable, spellID)
    usable, noPower = plain(usable), plain(noPower)
    if usable == true then add("ok") elseif usable == SECRET then add("ok=?") end
    if noPower == true then add("nopow") elseif noPower == SECRET then add("nopow=?") end

    local glow = try(C_SpellActivationOverlay and C_SpellActivationOverlay.IsSpellOverlayed, spellID)
    if plain(glow) == true then add("glow") end

    return table.concat(tokens, ",")
end

local function watchSnapshot()
    local parts = {}
    for spellID in pairs(watch) do
        parts[#parts + 1] = spellID .. ":" .. spellState(spellID)
    end
    table.sort(parts)
    return table.concat(parts, ";")
end

local RESTRICTION_NAMES = { [0] = "combat", [1] = "encounter", [2] = "challenge", [3] = "pvp", [4] = "map", [5] = "chat" }

-- What is secret right now? Taken at combat start, a few seconds in, at the end and after.
local function secrecyProbe()
    local p = { t = round(GetTime(), 3) }

    local restr = {}
    for id, name in pairs(RESTRICTION_NAMES) do
        local active, err = try(C_RestrictedActions and C_RestrictedActions.IsAddOnRestrictionActive, id)
        restr[name] = err and ("err:" .. err) or plain(active)
    end
    p.restrictions = restr

    if C_Secrets then
        p.secretsApi = {
            any = plain(try(C_Secrets.HasSecretRestrictions)),
            auras = plain(try(C_Secrets.ShouldAurasBeSecret)),
            cooldowns = plain(try(C_Secrets.ShouldCooldownsBeSecret)),
            stats = plain(try(C_Secrets.ShouldUnitStatsBeSecret)),
            playerPower = plain(try(C_Secrets.ShouldUnitPowerBeSecret, "player")),
        }
    end
    if C_CombatLog then
        p.combatLogRestricted = plain(try(C_CombatLog.IsCombatLogRestricted))
    end

    p.focus = num(try(UnitPower, "player"), 0)
    p.focusMax = num(try(UnitPowerMax, "player"), 0)
    p.haste = num(try(UnitSpellHaste, "player"), 2)

    -- Player aura access: by-index calls are documented to throw while auras are secret.
    local aura, auraErr = try(C_UnitAuras and C_UnitAuras.GetAuraDataByIndex, "player", 1, "HELPFUL")
    if auraErr then
        p.auraByIndex = "error: " .. string.sub(auraErr, 1, 80)
    elseif isTable(aura) then
        p.auraByIndex = (plain(aura.spellId) == SECRET) and "secret" or "readable"
    else
        p.auraByIndex = isSecret(aura) and "secret" or "none"
    end

    -- Target: only flags and the NPC id are stored, never a name.
    local exists = plain(try(UnitExists, "target"))
    if exists == true then
        local tgt = {}
        local guid = plain(try(UnitGUID, "target"))
        if guid == SECRET then
            tgt.guid = SECRET
        elseif type(guid) == "string" then
            local kind, _, _, _, _, npcID = strsplit("-", guid)
            tgt.guid = "readable"
            tgt.kind = kind
            if kind == "Creature" or kind == "Vehicle" then tgt.npcID = tonumber(npcID) end
        end
        local name = plain(try(UnitName, "target"))
        tgt.name = (name == SECRET) and SECRET or (name and "readable" or nil)
        tgt.health = num(try(UnitHealth, "target"), 0)
        tgt.healthMax = num(try(UnitHealthMax, "target"), 0)
        tgt.classification = plain(try(UnitClassification, "target"))
        tgt.level = plain(try(UnitLevel, "target"))
        tgt.canAttack = plain(try(UnitCanAttack, "player", "target"))
        p.target = tgt
    else
        p.target = false
    end
    return p
end

-- Post-combat per-spell damage from Blizzard's built-in meter.
local function damageMeterDump()
    local out = {}
    if not C_DamageMeter then
        out.status = "no C_DamageMeter"
        return out
    end
    local available, reason = try(C_DamageMeter.IsDamageMeterAvailable)
    out.available = plain(available)
    if plain(available) ~= true then
        out.reason = plain(reason)
        return out
    end

    local meterType = Enum and Enum.DamageMeterType and Enum.DamageMeterType.DamageDone or 0
    local current = Enum and Enum.DamageMeterSessionType and Enum.DamageMeterSessionType.Current or 1
    local playerGUID = try(UnitGUID, "player")

    local function summarize(src, err)
        if err then return { error = err } end
        if not isTable(src) then return { result = plain(src) or "nil" } end
        local res = { total = num(src.totalAmount, 0), spells = {} }
        local spells = src.combatSpells
        if isTable(spells) then
            for i = 1, math.min(#spells, 40) do
                local sp = spells[i]
                if isTable(sp) then
                    res.spells[#res.spells + 1] = { plain(sp.spellID), num(sp.totalAmount, 0) }
                end
            end
            res.spellCount = #spells
        else
            res.spells = plain(spells) or "nil"
        end
        return res
    end

    out.byType = summarize(try(C_DamageMeter.GetCombatSessionSourceFromType, current, meterType, playerGUID, nil))

    local sessions, sessErr = try(C_DamageMeter.GetAvailableCombatSessions)
    if sessErr then
        out.sessionsError = sessErr
    elseif isTable(sessions) then
        out.sessionCount = #sessions
        local last = sessions[#sessions]
        if isTable(last) then
            local id = plain(last.sessionID)
            out.lastSessionID = id
            out.lastSessionDuration = num(last.durationSeconds, 1)
            if type(id) == "number" then
                out.byID = summarize(try(C_DamageMeter.GetCombatSessionSourceFromID, id, meterType, playerGUID, nil))
            end
        end
    end
    return out
end

---------------------------------------------------------------------------
-- Session lifecycle
---------------------------------------------------------------------------

local function playerContext()
    local ctx = {}
    local _, classFile = UnitClass("player")
    ctx.class = plain(classFile)

    local specIndex = try(C_SpecializationInfo and C_SpecializationInfo.GetSpecialization or GetSpecialization)
    specIndex = plain(specIndex)
    if type(specIndex) == "number" then
        local getInfo = C_SpecializationInfo and C_SpecializationInfo.GetSpecializationInfo or GetSpecializationInfo
        ctx.specID = plain(try(getInfo, specIndex))
    end
    ctx.heroSpecID = plain(try(C_ClassTalents and C_ClassTalents.GetActiveHeroTalentSpec))

    local _, instanceType, difficultyID, _, _, _, _, instanceID = GetInstanceInfo()
    ctx.instanceType = plain(instanceType)
    ctx.difficultyID = plain(difficultyID)
    ctx.instanceID = plain(instanceID)
    return ctx
end

-- The watch list is kept per spec and only learns from casts made in or just before combat,
-- so mounts and other out-of-combat casts do not fill it up.
local function loadWatch(specID)
    local key = type(specID) == "number" and specID or 0
    DB.watch[key] = DB.watch[key] or {}
    watch = DB.watch[key]
    watchCount = 0
    for _ in pairs(watch) do watchCount = watchCount + 1 end
end

local function rememberSpell(spellID)
    if type(spellID) ~= "number" or watch[spellID] then return end
    if watchCount >= MAX_WATCH then return end
    watch[spellID] = true
    watchCount = watchCount + 1
    if not DB.spellNames[spellID] then
        DB.spellNames[spellID] = plain(try(C_Spell and C_Spell.GetSpellName, spellID)) or "?"
    end
end

local function addEvent(code, unitCode, spellID, extra)
    local now = GetTime()
    if session then
        local events = session.events
        if #events < MAX_EVENTS then
            events[#events + 1] = { round(now - session.t0, 3), code, unitCode, spellID, extra }
        else
            session.truncated = true
        end
    else
        prebuf[#prebuf + 1] = { now, code, unitCode, spellID, extra }
        while prebuf[1] and now - prebuf[1][1] > PREPULL_SECONDS do
            table.remove(prebuf, 1)
        end
    end
end

local function finalizeSession(reason)
    local s = session
    if not s then return end
    session = nil

    s.duration = round((s.tEnd or GetTime()) - s.t0, 2)
    s.endReason = reason
    s.issecretErrors = issecretErrors

    local counts = { casts = 0, secretSpell = 0, petCasts = 0, glows = 0, failed = 0 }
    for _, e in ipairs(s.events) do
        local code, unitCode, spellID = e[2], e[3], e[4]
        if code == "OK" then
            if unitCode == "p" then counts.casts = counts.casts + 1 else counts.petCasts = counts.petCasts + 1 end
            if spellID == SECRET then counts.secretSpell = counts.secretSpell + 1 end
        elseif code == "GLOW+" then
            counts.glows = counts.glows + 1
        elseif code == "FAIL" then
            counts.failed = counts.failed + 1
        end
    end
    s.counts = counts
    s.t0, s.tEnd = nil, nil
    if counts.casts == 0 and s.duration < 5 then return end   -- brief aggro with no casts

    local sessions = DB.sessions
    sessions[#sessions + 1] = s
    while #sessions > MAX_SESSIONS do table.remove(sessions, 1) end

    if reason == "restart" then return end   -- a new fight has started: stay silent in combat
    local dmSpells = s.damageMeter and (s.damageMeter.byType and s.damageMeter.byType.spellCount
        or s.damageMeter.byID and s.damageMeter.byID.spellCount) or 0
    print(string.format(
        "|cff66ccff[RT Probe]|r 세션 #%d 저장: %.0f초, 내 시전 %d회 (주문 ID 비밀 %d회), 펫 %d회, 반짝임 %d회, 피해 미터 스킬 %s개. /reload 하면 파일에 기록됩니다.",
        #sessions, s.duration, counts.casts, counts.secretSpell, counts.petCasts, counts.glows, tostring(dmSpells)))
end

local function startSession()
    if session then finalizeSession("restart") end
    if not enabled then return end

    local now = GetTime()
    session = {
        v = PROBE_VERSION,
        startedAt = date("%Y-%m-%d %H:%M:%S"),
        build = plain(select(2, GetBuildInfo())),
        interface = plain(select(4, GetBuildInfo())),
        t0 = now,
        context = playerContext(),
        events = {},
        probes = {},
        errors = {},
    }
    loadWatch(session.context.specID)
    -- Bring in pre-pull casts with negative timestamps.
    for _, e in ipairs(prebuf) do
        if now - e[1] <= PREPULL_SECONDS then
            session.events[#session.events + 1] = { round(e[1] - now, 3), e[2], e[3], e[4], e[5] }
            if e[2] == "OK" and e[3] == "p" then rememberSpell(e[4]) end
        end
    end
    prebuf = {}

    local this = session
    guarded("probe.start", function() this.probes.start = secrecyProbe() end)
    C_Timer.After(3, function()
        if session == this then
            guarded("probe.mid", function() this.probes.mid = secrecyProbe() end)
        end
    end)
end

local function endSession()
    local this = session
    if not this then return end
    this.tEnd = GetTime()
    guarded("probe.end", function() this.probes["end"] = secrecyProbe() end)
    C_Timer.After(2, function()
        if session ~= this then return end
        guarded("probe.after", function() this.probes.after = secrecyProbe() end)
        guarded("damageMeter", function() this.damageMeter = damageMeterDump() end)
        finalizeSession("combat_end")
    end)
end

---------------------------------------------------------------------------
-- Events
---------------------------------------------------------------------------

local CAST_CODES = {
    UNIT_SPELLCAST_SENT = "SENT",
    UNIT_SPELLCAST_START = "START",
    UNIT_SPELLCAST_STOP = "STOP",
    UNIT_SPELLCAST_SUCCEEDED = "OK",
    UNIT_SPELLCAST_FAILED = "FAIL",
    UNIT_SPELLCAST_INTERRUPTED = "INT",
    UNIT_SPELLCAST_CHANNEL_START = "CH+",
    UNIT_SPELLCAST_CHANNEL_STOP = "CH-",
    UNIT_SPELLCAST_EMPOWER_START = "EMP+",
    UNIT_SPELLCAST_EMPOWER_STOP = "EMP-",
}

local function onCastEvent(event, unit, arg2, arg3, arg4)
    -- UNIT_SPELLCAST_SENT: unit, targetName, castGUID, spellID. Others: unit, castGUID, spellID.
    local rawSpell = arg3
    if event == "UNIT_SPELLCAST_SENT" then rawSpell = arg4 end
    local unitToken = plain(unit)
    local unitCode = (unitToken == "player") and "p" or (unitToken == "pet") and "pet" or tostring(unitToken)
    local spellID = plain(rawSpell)
    local code = CAST_CODES[event]

    -- The cast itself is recorded even if the state snapshot fails.
    local extra
    if session and code == "OK" and unitCode == "p" then
        rememberSpell(spellID)
        local ok, snap = pcall(watchSnapshot)
        if ok then
            extra = snap
        else
            extra = "snaperr"
            logError("watchSnapshot", snap)
        end
    end
    addEvent(code, unitCode, spellID, extra)
end

local frame = CreateFrame("Frame")

local function onEvent(_, event, ...)
    if event == "ADDON_LOADED" then
        local name = ...
        if name ~= ADDON_NAME then return end
        RotationTeacherProbeDB = RotationTeacherProbeDB or {}
        DB = RotationTeacherProbeDB
        DB.sessions = DB.sessions or {}
        DB.spellNames = DB.spellNames or {}
        DB.errors = DB.errors or {}
        DB.restrictionLog = DB.restrictionLog or {}
        DB.watch = DB.watch or {}
        DB.probeVersion = PROBE_VERSION
        if DB.enabled == nil then DB.enabled = true end
        enabled = DB.enabled
        frame:UnregisterEvent("ADDON_LOADED")
        return
    end
    if not DB then return end

    if CAST_CODES[event] then
        guarded(event, onCastEvent, event, ...)
    elseif event == "PLAYER_REGEN_DISABLED" then
        guarded(event, startSession)
    elseif event == "PLAYER_REGEN_ENABLED" then
        guarded(event, endSession)
    elseif event == "SPELL_ACTIVATION_OVERLAY_GLOW_SHOW" then
        guarded(event, addEvent, "GLOW+", "p", plain((...)))
    elseif event == "SPELL_ACTIVATION_OVERLAY_GLOW_HIDE" then
        guarded(event, addEvent, "GLOW-", "p", plain((...)))
    elseif event == "ENCOUNTER_START" then
        local id, name, difficulty, size = ...
        if session then
            session.encounter = { id = plain(id), name = plain(name), difficulty = plain(difficulty), size = plain(size) }
        end
        guarded(event, addEvent, "ENC+", "-", plain(id))
    elseif event == "ENCOUNTER_END" then
        local id, _, _, _, success = ...
        if session and session.encounter then session.encounter.success = plain(success) end
        guarded(event, addEvent, "ENC-", "-", plain(id))
    elseif event == "CHALLENGE_MODE_START" then
        guarded(event, addEvent, "M+", "-", plain((...)))
    elseif event == "ADDON_RESTRICTION_STATE_CHANGED" then
        local restrictionType, state = ...
        local label = (RESTRICTION_NAMES[plain(restrictionType)] or tostring(plain(restrictionType))) .. "=" .. tostring(plain(state))
        guarded(event, addEvent, "RESTR", "-", label)
        local log = DB.restrictionLog
        if #log < 200 then log[#log + 1] = date("%H:%M:%S") .. " " .. label end
    end
end

frame:SetScript("OnEvent", onEvent)
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_REGEN_DISABLED")
frame:RegisterEvent("PLAYER_REGEN_ENABLED")
frame:RegisterEvent("ENCOUNTER_START")
frame:RegisterEvent("ENCOUNTER_END")
frame:RegisterEvent("CHALLENGE_MODE_START")
frame:RegisterEvent("SPELL_ACTIVATION_OVERLAY_GLOW_SHOW")
frame:RegisterEvent("SPELL_ACTIVATION_OVERLAY_GLOW_HIDE")
for event in pairs(CAST_CODES) do
    frame:RegisterUnitEvent(event, "player", "pet")
end
-- Newer event; registering an unknown event name would throw on older clients.
pcall(frame.RegisterEvent, frame, "ADDON_RESTRICTION_STATE_CHANGED")

---------------------------------------------------------------------------
-- Slash command
---------------------------------------------------------------------------

local function describeProbe(label, p)
    if type(p) ~= "table" then return label .. ": (없음)" end
    local r = p.restrictions or {}
    local tgt = type(p.target) == "table" and p.target or {}
    return string.format("%s: 집중=%s 가속=%s 오라=%s 대상GUID=%s 대상체력=%s | 제한 combat=%s encounter=%s map=%s",
        label, tostring(p.focus), tostring(p.haste), tostring(p.auraByIndex), tostring(tgt.guid), tostring(tgt.health),
        tostring(r.combat), tostring(r.encounter), tostring(r.map))
end

SLASH_ROTATIONTEACHERPROBE1 = "/rtp"
SlashCmdList["ROTATIONTEACHERPROBE"] = function(msg)
    msg = (msg or ""):lower():match("^%s*(.-)%s*$")
    local sessions = DB and DB.sessions or {}
    if msg == "clear" then
        DB.sessions, DB.errors, DB.restrictionLog, DB.watch = {}, {}, {}, {}
        watch, watchCount = {}, 0
        print("|cff66ccff[RT Probe]|r 기록을 모두 지웠습니다.")
    elseif msg == "on" or msg == "off" then
        enabled = (msg == "on")
        DB.enabled = enabled
        print("|cff66ccff[RT Probe]|r 기록 " .. (enabled and "켜짐" or "꺼짐"))
    elseif msg == "last" then
        local s = sessions[#sessions]
        if not s then print("|cff66ccff[RT Probe]|r 저장된 세션이 없습니다.") return end
        print(string.format("|cff66ccff[RT Probe]|r 세션 #%d (%s, %s초, 인스턴스=%s)", #sessions, tostring(s.startedAt),
            tostring(s.duration), tostring(s.context and s.context.instanceType)))
        print(describeProbe("  시작", s.probes.start))
        print(describeProbe("  3초", s.probes.mid))
        print(describeProbe("  종료", s.probes["end"]))
        print(describeProbe("  종료+2초", s.probes.after))
        if #s.errors > 0 then print("  오류 " .. #s.errors .. "건: " .. s.errors[1]) end
    else
        print(string.format("|cff66ccff[RT Probe]|r 세션 %d개 저장됨, 기록 %s. 명령: /rtp last · /rtp clear · /rtp on · /rtp off",
            #sessions, enabled and "켜짐" or "꺼짐"))
    end
end
