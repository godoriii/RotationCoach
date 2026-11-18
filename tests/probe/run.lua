-- Runs RotationTeacherProbe against the fake WoW environment.
--   lua5.1 tests/probe/run.lua        (from the repository root)

package.path = "tests/probe/?.lua;" .. package.path
local fake = require("fake_wow")
local PROBE = "RotationTeacherProbe/Probe.lua"

-- The fake environment replaces print(), so results go straight to stdout.
local function out(line) io.stdout:write(line, "\n") end

local passed, failed = 0, 0
local function check(cond, label)
    if cond then
        passed = passed + 1
    else
        failed = failed + 1
        out("FAIL: " .. label)
    end
end

-- SavedVariables can only hold plain data; a secret stored there would be lost (and is a bug).
local function assertPlain(v, path)
    local t = type(v)
    if t == "table" then
        for k, x in pairs(v) do
            check(type(k) == "string" or type(k) == "number", path .. ": key type " .. type(k))
            assertPlain(x, path .. "." .. tostring(k))
        end
    else
        check(t == "string" or t == "number" or t == "boolean", path .. ": stored a " .. t)
    end
end

local function find(events, code, spell)
    local out = {}
    for _, e in ipairs(events) do
        if e[2] == code and (spell == nil or e[4] == spell) then out[#out + 1] = e end
    end
    return out
end

local KC, RAPTOR, BOMB, PET_BITE = 259489, 186270, 259495, 17253

local function cast(env, spell, unit)
    env.fire("UNIT_SPELLCAST_SENT", unit or "player", "훈련용 허수아비", "Cast-GUID", spell)
    env.fire("UNIT_SPELLCAST_SUCCEEDED", unit or "player", "Cast-GUID", spell, 1)
end

---------------------------------------------------------------------------
-- 1. Training dummy in the open world: full flow
---------------------------------------------------------------------------
do
    local env = fake.install({})
    env.load(PROBE)
    local st = env.state

    cast(env, 783)                      -- mount-like cast long before the pull: must be forgotten
    env.advance(60)
    cast(env, BOMB)                     -- pre-pull cast, 2 s before combat
    env.advance(2)

    st.inCombat = true
    st.cooldowns[KC] = { charges = { 2, 2 } }
    env.fire("PLAYER_REGEN_DISABLED")
    check(#env.printed == 0, "nothing printed at combat start")

    cast(env, KC)
    st.cooldowns[KC] = { start = env.now, duration = 5, charges = { 1, 2 } }
    env.advance(1.4)
    st.glows[RAPTOR] = true
    env.fire("SPELL_ACTIVATION_OVERLAY_GLOW_SHOW", RAPTOR)
    st.noPower = RAPTOR
    cast(env, RAPTOR)
    env.fire("UNIT_SPELLCAST_SUCCEEDED", "pet", "Cast-GUID", PET_BITE, 1)
    env.advance(1.4)
    cast(env, fake.secret("spell"))     -- a spell flagged always-secret
    env.fire("UNIT_SPELLCAST_FAILED", "player", "Cast-GUID", RAPTOR, 1)
    env.advance(3)                      -- lets the +3 s probe run
    check(#env.printed == 0, "nothing printed during combat")

    st.inCombat = false
    env.fire("PLAYER_REGEN_ENABLED")
    env.advance(2.5)

    local db = RotationTeacherProbeDB
    check(#db.sessions == 1, "one session stored")
    local s = db.sessions[1]
    assertPlain(db, "DB")

    check(s.context.class == "HUNTER" and s.context.specID == 255 and s.context.heroSpecID == 42, "context captured")
    check(s.context.instanceType == "none", "instance type captured")
    check(s.counts.casts == 4, "4 player casts incl. pre-pull, got " .. tostring(s.counts.casts))
    check(s.counts.petCasts == 1, "pet cast counted")
    check(s.counts.secretSpell == 1, "secret spell id counted")
    check(s.counts.glows == 1 and s.counts.failed == 1, "glow and failed counted")
    check(s.duration > 5 and s.duration < 7, "duration ~5.8 s, got " .. tostring(s.duration))

    local pre = find(s.events, "OK", BOMB)[1]
    check(pre and pre[1] < 0, "pre-pull cast has a negative timestamp")
    check(#find(s.events, "OK", 783) == 0, "old out-of-combat cast not included")
    check(db.watch[255][783] == nil and db.watch[255][BOMB] == true, "watch list learns only combat/pre-pull casts")

    local raptor = find(s.events, "OK", RAPTOR)[1]
    local snap = raptor and raptor[5] or ""
    check(snap:find(KC .. ":[^;]*cd"), "KC cooldown active flag readable in combat: " .. snap)
    check(snap:find(KC .. ":[^;]*dur=%?"), "KC duration reported as secret")
    check(snap:find(KC .. ":[^;]*ch=%?/2"), "KC current charges secret, max readable")
    check(snap:find(KC .. ":[^;]*rech"), "KC recharging flag")
    check(snap:find(RAPTOR .. ":[^;]*nopow"), "insufficient power flag")
    check(snap:find(RAPTOR .. ":[^;]*glow"), "glow flag")

    local p = s.probes
    check(p.start and p.mid and p["end"] and p.after, "four probes taken")
    check(p.mid.focus == "<secret>" and p.mid.haste == "<secret>", "focus/haste secret in combat")
    check(p.after.haste == 12.34, "haste readable after combat")
    check(p.mid.auraByIndex:find("^error"), "aura by index throws in combat")
    check(p.after.auraByIndex == "readable", "aura readable after combat")
    check(p.mid.restrictions.combat == true and p.after.restrictions.combat == false, "restriction state")
    check(p.mid.target.guid == "readable" and p.mid.target.npcID == 225984, "open-world target npc id")
    check(p.mid.target.health == "<secret>", "target health secret")
    check(p.mid.target.name == "readable", "target name stored only as a flag")

    check(s.damageMeter.byType.total == 123456 and s.damageMeter.byType.spellCount == 2, "damage meter by type")
    check(s.damageMeter.byID.spells[1][1] == KC, "damage meter by id")
    check(db.spellNames[KC] == "주문" .. KC, "spell name stored")
    check(#s.errors == 0, "no recorder errors: " .. tostring(s.errors[1]))
    check(#env.printed == 1 and env.printed[1]:find("세션 #1"), "one summary line after combat")

    SlashCmdList["ROTATIONTEACHERPROBE"]("last")
    check(#env.printed >= 5, "/rtp last prints the probes")
    SlashCmdList["ROTATIONTEACHERPROBE"]("clear")
    check(#RotationTeacherProbeDB.sessions == 0, "/rtp clear")
end

---------------------------------------------------------------------------
-- 2. Instance, older client without the new APIs, cooldown API throwing
---------------------------------------------------------------------------
do
    local env = fake.install({ instanceType = "raid", difficultyID = 16, instanceID = 2800,
        noSecretsApi = true, noDamageMeter = true, cooldownThrows = true })
    env.load(PROBE)
    env.state.inCombat = true
    env.fire("PLAYER_REGEN_DISABLED")
    env.fire("ENCOUNTER_START", 3012, "보스", 16, 20)
    cast(env, KC)
    env.advance(1.5)
    cast(env, RAPTOR)
    env.advance(4)
    env.fire("ENCOUNTER_END", 3012, "보스", 16, 20, 1)
    env.state.inCombat = false
    env.fire("PLAYER_REGEN_ENABLED")
    env.advance(3)

    local db = RotationTeacherProbeDB
    assertPlain(db, "DB2")
    local s = db.sessions[1]
    check(s ~= nil, "session stored without optional APIs")
    check(s.counts.casts == 2, "casts still recorded when the cooldown API throws")
    check(s.encounter.id == 3012 and s.encounter.success == 1 and s.encounter.difficulty == 16, "encounter info")
    check(s.context.instanceType == "raid" and s.context.instanceID == 2800, "raid context")
    check(s.probes.mid.target.guid == "<secret>", "instance target guid secret")
    check(s.damageMeter.status == "no C_DamageMeter", "missing damage meter reported")
    local snap = find(s.events, "OK", RAPTOR)[1][5]
    check(snap:find("cderr"), "cooldown error marked in snapshot: " .. tostring(snap))
end

---------------------------------------------------------------------------
-- 3. Combat restarts before the post-combat step; brief aggro without casts is dropped
---------------------------------------------------------------------------
do
    local env = fake.install({})
    env.load(PROBE)
    env.state.inCombat = true
    env.fire("PLAYER_REGEN_DISABLED")
    cast(env, KC)
    env.advance(6)
    env.fire("PLAYER_REGEN_ENABLED")
    env.advance(1)                          -- post-combat timer (2 s) not fired yet
    env.fire("PLAYER_REGEN_DISABLED")       -- new fight
    check(#env.printed == 0, "no chat output when a new fight starts")
    check(#RotationTeacherProbeDB.sessions == 1, "first fight saved on restart")
    env.advance(2)
    env.fire("PLAYER_REGEN_ENABLED")        -- 2 s fight with no casts
    env.advance(3)
    check(#RotationTeacherProbeDB.sessions == 1, "empty short fight dropped")
    assertPlain(RotationTeacherProbeDB, "DB3")

    SlashCmdList["ROTATIONTEACHERPROBE"]("off")
    env.fire("PLAYER_REGEN_DISABLED")
    cast(env, KC)
    env.advance(8)
    env.fire("PLAYER_REGEN_ENABLED")
    env.advance(3)
    check(#RotationTeacherProbeDB.sessions == 1, "/rtp off stops recording")
end

out(string.format("%d passed, %d failed", passed, failed))
os.exit(failed == 0 and 0 or 1)
