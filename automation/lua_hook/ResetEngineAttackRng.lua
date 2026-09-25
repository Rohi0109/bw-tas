-- Experiment executable redirects this native Lua binding to the engine
-- RNG seeder. Do not install this hook without the matching binary bridge.
function BattleEngine:AutomationResetAttackRng()
  math.randomseed(1)
  print("AUTOMATION_RNG_RESET=" .. tostring(gAutomationAttackId) .. "|1|submit|engine|E")
end
