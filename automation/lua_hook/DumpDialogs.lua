function BattleEngine:AutomationDumpDialogs()
  local enemy = self.mEnemyPtr
  if enemy ~= nil and enemy.mName ~= nil then
    local currentEnemyName = enemy.mName
    if gAutomationZeroHealthEnemy ~= nil and currentEnemyName ~= gAutomationZeroHealthEnemy then
      gAutomationZeroHealthEnemy = nil
      gAutomationResetReadyEnemy = nil
      gAutomationLastDeathFlags = nil
    end
    if enemy.mHealth ~= nil and enemy.mHealth <= 0 then
      local deathFlags = tostring(enemy.mStateAnimsDone) .. "|" ..
        tostring(self.mDidDeathState) .. "|" .. tostring(self.mDidFinalDeathSequence) .. "|" ..
        tostring(self.mInterruptState) .. "|" .. tostring(self.mBossState) .. "|" ..
        tostring(self.mCheckpointState)
      if gAutomationLastDeathFlags ~= deathFlags then
        gAutomationLastDeathFlags = deathFlags
        print("AUTOMATION_DEATH_FLAGS=" .. currentEnemyName .. "|" .. deathFlags .. "|E")
      end
      if gAutomationZeroHealthEnemy ~= currentEnemyName then
        gAutomationZeroHealthEnemy = currentEnemyName
        gAutomationResetReadyEnemy = nil
        print("AUTOMATION_ZERO_HEALTH=" .. currentEnemyName .. "|E")
      end
    elseif gAutomationZeroHealthEnemy == currentEnemyName then
      gAutomationZeroHealthEnemy = nil
      gAutomationResetReadyEnemy = nil
      gAutomationLastDeathFlags = nil
    end
    if gAutomationTrackedEnemyName == nil then
      gAutomationTrackedEnemyName = currentEnemyName
    elseif currentEnemyName ~= gAutomationTrackedEnemyName then
      print("AUTOMATION_DEFEATED=" .. gAutomationTrackedEnemyName .. "|E")
      gAutomationTrackedEnemyName = currentEnemyName
    end
  end

  -- Match BattleEngine:MouseUp ownership. mNeedsLevelUp is merely a request
  -- flag and can remain stale after PLAY; mLevelupEffect is the clickable UI.
  local dialogSource = nil
  if self.mLevelupEffect ~= nil then
    dialogSource = "levelup"
  elseif convpanel ~= nil and convpanel.Active ~= nil and convpanel.Active() then
    dialogSource = "convpanel"
  elseif gAutomationSawPlayTutorial and self.mInterruptState then
    -- PLAY overlaps a nonzero checkpoint state, but its click owner is the
    -- scripted IntroTutorial interrupt.
    dialogSource = "interrupt"
  elseif self.mCheckpointState ~= nil and self.mCheckpointState > 0 then
    dialogSource = "checkpoint"
  elseif self.mInterruptState then
    dialogSource = "interrupt"
  end

  if enemy ~= nil and enemy.mStateAnimsDone and self.mDidFinalDeathSequence and
      not self.mInterruptState and gAutomationZeroHealthEnemy ~= nil and
      gAutomationResetReadyEnemy ~= gAutomationZeroHealthEnemy then
    gAutomationResetReadyEnemy = gAutomationZeroHealthEnemy
    print("AUTOMATION_BOSS_RESET_READY=" .. gAutomationZeroHealthEnemy .. "|E")
  end

  if gAutomationDialogSequence == nil then gAutomationDialogSequence = 0 end
  if gAutomationDialogUpdates == nil then gAutomationDialogUpdates = 0 end
  if gAutomationDialogPulse == nil then gAutomationDialogPulse = 0 end
  if dialogSource ~= gAutomationDialogSource then
    if gAutomationDialogSource ~= nil then
      print("AUTOMATION_DIALOG_INACTIVE=" .. gAutomationDialogSequence .. "|E")
    end
    gAutomationDialogSource = dialogSource
    gAutomationDialogUpdates = 0
    gAutomationDialogPulse = 0
    if dialogSource ~= nil then
      gAutomationDialogSequence = gAutomationDialogSequence + 1
      print("AUTOMATION_DIALOG_ACTIVE=" .. dialogSource .. "|" ..
        gAutomationDialogSequence .. "|E")
      if dialogSource == "interrupt" and gAutomationSawPlayTutorial then
        print("AUTOMATION_PLAY_TUTORIAL=" .. gAutomationDialogSequence .. "|E")
      end
    end
  end

  if dialogSource ~= nil then
    gAutomationDialogUpdates = gAutomationDialogUpdates + 1
    -- First authorization after three native updates, then every fifteen.
    if gAutomationDialogUpdates >= 3 and ((gAutomationDialogUpdates - 3) % 15) == 0 then
      gAutomationDialogPulse = gAutomationDialogPulse + 1
      print("AUTOMATION_DIALOG_PULSE=" .. dialogSource .. "|" ..
        gAutomationDialogSequence .. "|" .. gAutomationDialogPulse .. "|E")
    end
  end

  if dialogSource == nil and gAutomationZeroHealthEnemy ~= nil and
      gAutomationResetReadyEnemy == gAutomationZeroHealthEnemy then
    gAutomationZeroHealthEnemy = nil
    gAutomationResetReadyEnemy = nil
  end
end
