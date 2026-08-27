function BattleEngine:AutomationDumpDialogs()
  local enemy = self.mEnemyPtr
  if enemy ~= nil and enemy.mName ~= nil then
    local currentEnemyName = enemy.mName
    if gAutomationTrackedEnemyName == nil then
      gAutomationTrackedEnemyName = currentEnemyName
    elseif currentEnemyName ~= gAutomationTrackedEnemyName then
      print("AUTOMATION_DEFEATED=" .. gAutomationTrackedEnemyName .. "|E")
      gAutomationTrackedEnemyName = currentEnemyName
    end
  end

  local dialogType = "none"
  if self.mInterruptState then
    if self.mNeedsLevelUp or self.mLevelUpData ~= nil then
      dialogType = "levelup"
    end
  end
  if dialogType == "none" and convpanel ~= nil and convpanel.Active ~= nil then
    if convpanel.Active() then dialogType = "conversation" end
  end

  if gAutomationDialogTicks == nil then gAutomationDialogTicks = 0 end
  if dialogType == "conversation" then
    gAutomationDialogTicks = gAutomationDialogTicks + 1
  else
    gAutomationDialogTicks = 0
  end
  if gAutomationLastDialog == nil then gAutomationLastDialog = "none" end
  local emitDialog = dialogType ~= gAutomationLastDialog
  if dialogType == "conversation" and gAutomationDialogTicks >= 30 then
    emitDialog = true
  end
  if emitDialog then
    gAutomationLastDialog = dialogType
    gAutomationDialogTicks = 0
    if gAutomationDialogSequence == nil then gAutomationDialogSequence = 0 end
    gAutomationDialogSequence = gAutomationDialogSequence + 1
    print("AUTOMATION_SYNC=1")
    print("AUTOMATION_SYNC=2")
    print("AUTOMATION_SYNC=3")
    print("AUTOMATION_DIALOG=" .. dialogType .. "|" ..
      gAutomationDialogSequence .. "|E")
  end
end
