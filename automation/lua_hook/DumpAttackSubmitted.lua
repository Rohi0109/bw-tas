function BattleEngine:AutomationAttackSubmitted(word)
  local enemyName = "unknown"
  if self.mEnemyPtr ~= nil and self.mEnemyPtr.mName ~= nil then
    enemyName = self.mEnemyPtr.mName
  end
  print("AUTOMATION_ATTACK_SUBMITTED=" .. enemyName .. "|E")
  gAutomationSubmittedWord = word
  gAutomationNativeValuePending = true
end
