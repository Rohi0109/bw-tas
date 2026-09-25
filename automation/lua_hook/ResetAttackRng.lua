-- Experiment only: run after submission telemetry, before the original
-- SubmitTiles body. Preserve the native RNG implementation and its call ABI.
function BattleEngine:AutomationResetAttackRng()
  math.randomseed(1)
  print("AUTOMATION_RNG_RESET=" .. tostring(gAutomationAttackId) .. "|1|submit|E")
end
