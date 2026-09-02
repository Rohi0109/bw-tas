function BattleEngine:AutomationDumpDialogs()
  -- IntroTutorial itself exposes the exact input gate used by TileClicked.
  -- Authorize only the currently requested letter while state 2 owns input;
  -- MouseUp changes mNextLetter synchronously, so a retry can never spill into
  -- the next tutorial step (or the live combat rack).
  local playLetter = nil
  if IntroTutorial ~= nil and IntroTutorial.mState == 2 and
      IntroTutorial.mNextLetter ~= nil then
    playLetter = tostring(IntroTutorial.mNextLetter)
  end
  local playClickable = false
  if playLetter == "" then
    -- CanAttack remains false while IntroTutorial owns the interrupt even
    -- though its final instruction explicitly expects the Attack button.
    playClickable = true
  elseif playLetter ~= nil and gTileEngine ~= nil and gBoard ~= nil then
    local playX = nil
    local playY = nil
    if playLetter == "P" then playX = 0; playY = 1 end
    if playLetter == "L" then playX = 1; playY = 3 end
    if playLetter == "A" then playX = 2; playY = 0 end
    if playLetter == "Y" then playX = 3; playY = 2 end
    if playX ~= nil then
      local playTileKey = gBoard.GridGetTile(gBoard, playX, playY)
      local playTile = gTileTable[playTileKey]
      playClickable = playTile ~= nil and
        gTileEngine.CanSelect(gTileEngine, playTileKey, playX, playY)
      if playClickable and playTile.IsMoving ~= nil and
          playTile.IsMoving(playTile) then
        playClickable = false
      end
      if playClickable and playTile.IsFalling ~= nil and
          playTile.IsFalling(playTile) then
        playClickable = false
      end
    end
  end
  local playAuthorization = playLetter
  if not playClickable then playAuthorization = nil end
  if playAuthorization ~= gAutomationPlayLetter then
    gAutomationPlayLetter = playAuthorization
    gAutomationPlayReadyUpdates = 0
    gAutomationPlayReadyPulse = 0
  end
  if playAuthorization ~= nil then
    gAutomationPlayReadyUpdates = gAutomationPlayReadyUpdates + 1
    if gAutomationPlayReadyUpdates == 1 or
        (gAutomationPlayReadyUpdates % 15) == 0 then
      gAutomationPlayReadyPulse = gAutomationPlayReadyPulse + 1
      local emittedLetter = playAuthorization
      if emittedLetter == "" then emittedLetter = "DONE" end
      print("AUTOMATION_PLAY_READY=" .. emittedLetter .. "|" ..
        gAutomationPlayReadyPulse .. "|E")
    end
  end

  -- TileEngine stops reaching its board logger while an enemy-owned modal
  -- overlay has control. In particular, Hydra Head 4 can open with Freezing
  -- Breath before another actionable board snapshot exists. Report that edge
  -- from BattleEngine, which continues updating while the Frozen card is up.
  local livePlayerFrozen = false
  local freezeFrame = "none"
  if self.mGridOverlayPAM ~= nil and
      self.mGridOverlayPAM.mPlayingFrame ~= nil then
    freezeFrame = tostring(self.mGridOverlayPAM.mPlayingFrame)
    livePlayerFrozen = freezeFrame == "frozen" or
      freezeFrame == "frozenloop" or freezeFrame == "breakfrozen"
  end
  if gAutomationLivePlayerFrozen == nil then
    gAutomationLivePlayerFrozen = false
  end
  local playerHealth = -1
  local playerMaxHealth = -1
  local healthPotionAvailable = false
  local purifyPotionAvailable = false
  if self.mPlayerPtr ~= nil then
    local player = self.mPlayerPtr
    if player.mHealth ~= nil then playerHealth = player.mHealth end
    if player.mMaxHealth ~= nil then playerMaxHealth = player.mMaxHealth end
    if player.HasHealthPotion ~= nil then
      healthPotionAvailable = player:HasHealthPotion()
    end
    if player.HasPurifyPotion ~= nil then
      purifyPotionAvailable = player:HasPurifyPotion()
    end
  end
  if livePlayerFrozen ~= gAutomationLivePlayerFrozen then
    gAutomationLivePlayerFrozen = livePlayerFrozen
    print("AUTOMATION_PLAYER_FROZEN=" ..
      (livePlayerFrozen and "1" or "0") .. "|" ..
      playerHealth .. "|" .. playerMaxHealth .. "|" ..
      (healthPotionAvailable and "1" or "0") .. "|" ..
      (purifyPotionAvailable and "1" or "0") .. "|E")
  end
  if livePlayerFrozen and self.mGridOverlayPAM ~= nil then
    local overlayState = "frozen|" .. freezeFrame .. "|" ..
      playerHealth .. "|" .. playerMaxHealth .. "|" ..
      (healthPotionAvailable and "1" or "0") .. "|" ..
      (purifyPotionAvailable and "1" or "0")
    if gAutomationIncapOverlayState ~= overlayState then
      gAutomationIncapOverlayState = overlayState
      print("AUTOMATION_INCAP_OVERLAY=" .. overlayState .. "|E")
    end
  end

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
