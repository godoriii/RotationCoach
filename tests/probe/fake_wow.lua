-- Minimal fake of the WoW addon environment for running RotationTeacherProbe outside the game.
-- It imitates secret values with opaque userdata that raise an error on arithmetic, ordering,
-- indexing, length, concatenation and calls. Lua 5.1 cannot make `secret == x` raise for mixed
-- types, so equality misuse is not caught here; that part is covered by code review.

local M = {}

local secrets = setmetatable({}, { __mode = "k" })
local function boom(op) return function() error("attempt to " .. op .. " a secret value", 2) end end

function M.secret(label)
    local u = newproxy(true)
    local mt = getmetatable(u)
    mt.__add, mt.__sub, mt.__mul, mt.__div, mt.__unm = boom("do arithmetic on"), boom("do arithmetic on"),
        boom("do arithmetic on"), boom("do arithmetic on"), boom("do arithmetic on")
    mt.__lt, mt.__le = boom("compare"), boom("compare")
    mt.__index, mt.__newindex = boom("index"), boom("index")
    mt.__len, mt.__concat, mt.__call = boom("take length of"), boom("concatenate"), boom("call")
    mt.__tostring = function() return "SECRET(" .. tostring(label) .. ")" end
    secrets[u] = true
    return u
end

function M.install(opts)
    opts = opts or {}
    local env = { now = 1000, timers = {}, frames = {}, printed = {}, state = {} }
    local st = env.state
    st.inCombat = false          -- drives which values are secret
    st.cooldowns = {}            -- spellID -> { start, duration, charges = {cur, max} }
    st.glows = {}
    st.targetExists = true

    _G.issecretvalue = function(v) return secrets[v] == true end
    _G.GetTime = function() return env.now end
    _G.date = function(fmt) return os.date(fmt, 1700000000) end
    _G.print = function(...) env.printed[#env.printed + 1] = table.concat({ ... }, " ") end
    _G.strsplit = function(sep, str)
        local out = {}
        for piece in string.gmatch(str, "([^" .. sep .. "]+)") do out[#out + 1] = piece end
        return unpack(out)
    end
    _G.GetBuildInfo = function() return "12.1.5", "70783", "Nov 4 2026", 120105 end
    _G.UnitClass = function() return "사냥꾼", "HUNTER", 3 end
    _G.GetInstanceInfo = function()
        return "Stormwind", opts.instanceType or "none", opts.difficultyID or 0, "", 0, 0, false, opts.instanceID or 0
    end
    _G.GetSpecialization = function() return 3 end
    _G.GetSpecializationInfo = function() return 255, "생존" end
    _G.C_SpecializationInfo = nil
    _G.C_ClassTalents = { GetActiveHeroTalentSpec = function() return 42 end }
    _G.Enum = { DamageMeterType = { DamageDone = 0 }, DamageMeterSessionType = { Current = 1 } }

    local function maybeSecret(v, label)
        if st.inCombat then return M.secret(label) end
        return v
    end

    _G.UnitPower = function() return M.secret("focus") end          -- primary resource: always secret
    _G.UnitPowerMax = function() return 100 end
    _G.UnitSpellHaste = function() return maybeSecret(12.34, "haste") end
    _G.UnitExists = function() return st.targetExists end
    _G.UnitGUID = function(unit)
        if unit == "player" then return "Player-1-0000ABCD" end
        if opts.instanceType and opts.instanceType ~= "none" then return M.secret("guid") end
        return "Creature-0-3134-2552-1-225984-000ABCDEF0"
    end
    _G.UnitName = function() return "훈련용 허수아비" end
    _G.UnitHealth = function() return M.secret("health") end
    _G.UnitHealthMax = function() return M.secret("healthMax") end
    _G.UnitClassification = function() return "normal" end
    _G.UnitLevel = function() return 90 end
    _G.UnitCanAttack = function() return true end

    _G.C_Spell = {
        GetSpellName = function(id) return "주문" .. id end,
        GetSpellCooldown = function(id)
            if opts.cooldownThrows then error("cooldown api exploded") end
            local cd = st.cooldowns[id] or {}
            local active = cd.start ~= nil and (cd.start + cd.duration) > env.now
            return {
                startTime = maybeSecret(active and cd.start or 0, "start"),
                duration = maybeSecret(active and cd.duration or 0, "duration"),
                isEnabled = true, isActive = active, isOnGCD = false, modRate = 1,
            }
        end,
        GetSpellCharges = function(id)
            local cd = st.cooldowns[id]
            if not (cd and cd.charges) then return nil end
            return {
                currentCharges = maybeSecret(cd.charges[1], "charges"), maxCharges = cd.charges[2],
                cooldownStartTime = maybeSecret(0, "cstart"), cooldownDuration = maybeSecret(5, "cdur"),
                chargeModRate = 1, isActive = cd.charges[1] < cd.charges[2],
            }
        end,
        IsSpellUsable = function(id) return true, st.noPower == id end,
    }
    _G.C_SpellActivationOverlay = { IsSpellOverlayed = function(id) return st.glows[id] == true end }
    _G.C_UnitAuras = {
        GetAuraDataByIndex = function()
            if st.inCombat then error("auras are secret") end
            return { spellId = 260286, name = "창끝" }
        end,
    }

    if not opts.noSecretsApi then
        _G.C_RestrictedActions = {
            IsAddOnRestrictionActive = function(t) return t == 0 and st.inCombat end,
        }
        _G.C_Secrets = {
            HasSecretRestrictions = function() return st.inCombat end,
            ShouldAurasBeSecret = function() return st.inCombat end,
            ShouldCooldownsBeSecret = function() return st.inCombat end,
            ShouldUnitStatsBeSecret = function() return st.inCombat end,
            ShouldUnitPowerBeSecret = function() return true end,
        }
        _G.C_CombatLog = { IsCombatLogRestricted = function() return true end }
    else
        _G.C_RestrictedActions, _G.C_Secrets, _G.C_CombatLog = nil, nil, nil
    end

    if not opts.noDamageMeter then
        _G.C_DamageMeter = {
            IsDamageMeterAvailable = function() return true, "" end,
            GetCombatSessionSourceFromType = function()
                if st.inCombat then return M.secret("dm") end
                return { totalAmount = 123456, maxAmount = 9, combatSpells = {
                    { spellID = 259489, totalAmount = 50000 }, { spellID = 186270, totalAmount = 73456 } } }
            end,
            GetAvailableCombatSessions = function() return { { sessionID = 7, name = "x", durationSeconds = 30.5 } } end,
            GetCombatSessionSourceFromID = function()
                return { totalAmount = 123456, combatSpells = { { spellID = 259489, totalAmount = 50000 } } }
            end,
        }
    else
        _G.C_DamageMeter = nil
    end

    _G.C_Timer = {
        After = function(delay, fn) env.timers[#env.timers + 1] = { at = env.now + delay, fn = fn } end,
    }
    _G.SlashCmdList = {}
    _G.RotationTeacherProbeDB = opts.savedDB

    _G.CreateFrame = function()
        local f = { events = {}, unitEvents = {} }
        function f:RegisterEvent(e)
            if e == "ADDON_RESTRICTION_STATE_CHANGED" and opts.noSecretsApi then error("unknown event") end
            self.events[e] = true
        end
        function f:UnregisterEvent(e) self.events[e] = nil end
        function f:RegisterUnitEvent(e, ...) self.unitEvents[e] = { ... } end
        function f:SetScript(_, fn) self.handler = fn end
        env.frames[#env.frames + 1] = f
        return f
    end

    function env.fire(event, ...)
        for _, f in ipairs(env.frames) do
            if f.handler and (f.events[event] or f.unitEvents[event]) then f.handler(f, event, ...) end
        end
    end

    function env.advance(seconds)
        local target = env.now + seconds
        while true do
            local nextIdx, nextAt
            for i, t in ipairs(env.timers) do
                if t.at <= target and (not nextAt or t.at < nextAt) then nextIdx, nextAt = i, t.at end
            end
            if not nextIdx then break end
            local t = table.remove(env.timers, nextIdx)
            env.now = t.at
            t.fn()
        end
        env.now = target
    end

    function env.load(path)
        local chunk = assert(loadfile(path))
        chunk("RotationTeacherProbe", {})
        env.fire("ADDON_LOADED", "RotationTeacherProbe")
    end

    return env
end

return M
