function BattleEngine:AutomationDumpDialogs()
  local enemy = self.mEnemyPtr
  if enemy ~= nil and enemy.mName ~= nil then
    local currentEnemyName = enemy.mName
    -- Enemy-pointer changes occur after chapter/treasure transitions, which is
    -- too late for a post-boss animation skip.  Health reaches zero while the
    -- defeated boss is still the active encounter, so expose that edge once.
    if enemy.mHealth ~= nil and enemy.mHealth <= 0 then
      if gAutomationZeroHealthEnemy ~= currentEnemyName then
        gAutomationZeroHealthEnemy = currentEnemyName
        gAutomationResetReadyEnemy = nil
        print("AUTOMATION_ZERO_HEALTH=" .. currentEnemyName .. "|E")
      end
    elseif gAutomationZeroHealthEnemy == currentEnemyName then
      gAutomationZeroHealthEnemy = nil
      gAutomationResetReadyEnemy = nil
    end
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

  -- Every live boss sample enters the level-up/result interrupt after zero HP
  -- and before victory conversation.  This is the first Lua-confirmed state
  -- matching the WR's settled corpse/RIP frame where Menu is safe to open.
  if dialogType == "levelup" and gAutomationZeroHealthEnemy ~= nil and
      gAutomationResetReadyEnemy ~= gAutomationZeroHealthEnemy then
    gAutomationResetReadyEnemy = gAutomationZeroHealthEnemy
    print("AUTOMATION_BOSS_RESET_READY=" ..
      gAutomationZeroHealthEnemy .. "|E")
  end

  if gAutomationDialogTicks == nil then gAutomationDialogTicks = 0 end
  local repeatBossResult = dialogType == "levelup" and
    gAutomationZeroHealthEnemy ~= nil and
    string.find(gAutomationZeroHealthEnemy, "(Boss)", 1, true) ~= nil
  if dialogType == "conversation" or repeatBossResult then
    gAutomationDialogTicks = gAutomationDialogTicks + 1
  else
    gAutomationDialogTicks = 0
  end
  if gAutomationLastDialog == nil then gAutomationLastDialog = "none" end
  local emitDialog = dialogType ~= gAutomationLastDialog
  -- Multi-page result/level-up panels can remain the same dialog type after a
  -- Continue click.  Re-emit their still-active state so the controller can
  -- advance each page and wait for an explicit `none` edge before opening Menu.
  if (dialogType == "conversation" or repeatBossResult) and
      gAutomationDialogTicks >= 30 then
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
  if dialogType == "none" and gAutomationZeroHealthEnemy ~= nil and
      gAutomationResetReadyEnemy == gAutomationZeroHealthEnemy then
    gAutomationZeroHealthEnemy = nil
    gAutomationResetReadyEnemy = nil
  end
end
