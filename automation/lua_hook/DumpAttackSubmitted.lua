function BattleEngine:AutomationAttackSubmitted()
  local enemyName = "unknown"
  if self.mEnemyPtr ~= nil and self.mEnemyPtr.mName ~= nil then
    enemyName = self.mEnemyPtr.mName
  end
  print("AUTOMATION_ATTACK_SUBMITTED=" .. enemyName .. "|E")
end
