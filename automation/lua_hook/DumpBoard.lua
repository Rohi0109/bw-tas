TileEngine = {}

function TileEngine:AutomationDumpBoard()
  -- Count Lua RNG draws after the first complete board hook. The executable's
  -- MSVCRT stream is deterministic (seed 1), but the initial native setup has
  -- already consumed an unknown prefix. A relative cursor lets recorded
  -- transitions align that stream without changing random results.
  if gAutomationOriginalRandom == nil and math ~= nil and math.random ~= nil then
    gAutomationOriginalRandom = math.random
    gAutomationRandomCalls = 0
    math.random = function(first, second)
      local result = nil
      if first == nil then
        result = gAutomationOriginalRandom()
      elseif second == nil then
        result = gAutomationOriginalRandom(first)
      else
        result = gAutomationOriginalRandom(first, second)
      end
      gAutomationRandomCalls = gAutomationRandomCalls + 1
      return result
    end
  end
  local snapshot = ""
  local gems = ""
  local powers = ""
  local letterRows = {}
  local gemRows = {}
  local powerRows = {}
  local zeroDamageRows = {}
  local selectableRows = {}
  local complete = true
  local anySelectable = false
  local settled = true

  for y = 0, gTilesHigh - 1 do
    local letterRow = ""
    local gemRow = ""
    local powerRow = ""
    local selectableRow = ""
    local zeroDamageRow = ""
    if y > 0 then
      snapshot = snapshot .. "/"
    end
    for x = 0, gTilesWide - 1 do
      local tileKey = gBoard.GridGetTile(gBoard, x, y)
      local tile = gTileTable[tileKey]
      if tile == nil or tile.mLetter == nil then
        snapshot = snapshot .. "?"
        complete = false
      else
        snapshot = snapshot .. tile.mLetter
        letterRow = letterRow .. tile.mLetter
        local gemType = "none"
        if tile.mAttributes ~= nil then
          for _, attribute in pairs(tile.mAttributes) do
            if attribute.mBonusType ~= nil then
              gemType = attribute.mBonusType
            end
          end
        end
        local gemCode = "n"
        if gemType ~= "none" then gemCode = string.sub(gemType, 1, 1) end
        if gems ~= "" then
          gems = gems .. ","
        end
        gems = gems .. gemType
        if gemRow ~= "" then gemRow = gemRow .. "," end
        gemRow = gemRow .. gemCode
        local letterPower = 1
        if LETTER_BONUSES ~= nil and LETTER_BONUSES[tile.mLetter] ~= nil then
          letterPower = letterPower + LETTER_BONUSES[tile.mLetter]
        end
        local tilePower = tile.ApplyBonus(tile, letterPower)
        -- Smashed and plagued attributes suppress the tile's base letter
        -- value through ModifyValue; they do not expose that suppression via
        -- ApplyBonus. Mirror TileEngine:GetWordValue so the runner sees the
        -- same zero-damage tiles as the game.
        local modifiedLetterPower = tile.ModifyValue(tile, letterPower)
        if modifiedLetterPower <= 0 then
          zeroDamageRow = zeroDamageRow .. "1"
        else
          zeroDamageRow = zeroDamageRow .. "0"
        end
        if powers ~= "" then powers = powers .. "," end
        powers = powers .. tilePower
        if powerRow ~= "" then powerRow = powerRow .. "," end
        powerRow = powerRow .. tilePower
        -- Use a normal table call instead of ':' so the appended method does
        -- not require PopCap's problematic SELF opcode.
        local canSelect = self.CanSelect(self, tileKey, x, y)
        if canSelect then
          selectableRow = selectableRow .. "1"
        else
          selectableRow = selectableRow .. "0"
        end
        if not anySelectable and canSelect then
          anySelectable = true
        end
        if tile.IsMoving ~= nil and tile.IsMoving(tile) then
          settled = false
        end
        if tile.IsFalling ~= nil and tile.IsFalling(tile) then
          settled = false
        end
      end
    end
    letterRows[y] = letterRow
    gemRows[y] = gemRow
    powerRows[y] = powerRow
    selectableRows[y] = selectableRow
    zeroDamageRows[y] = zeroDamageRow
  end

  local fixedPlayBoard = "SFAE/PFUN/RJDY/TLIS"
  if complete and snapshot == fixedPlayBoard then
    gAutomationSawPlayTutorial = true
  end
  if complete and snapshot ~= gAutomationLastBoard then
    gAutomationLastBoard = snapshot
    print("AUTOMATION_BOARD=" .. snapshot)
  end

  local interrupted = false
  if gBattleEngine ~= nil and gBattleEngine.mInterruptState then
    interrupted = true
  end
  -- IntroTutorial leaves BattleEngine.mInterruptState asserted briefly after
  -- PLAY has replaced the fixed rack and returned tile control. At that point
  -- the changed, settled, selectable board is the native handoff signal; do
  -- not wait for blind dialogue probes to clear a stale tutorial flag.
  local postPlayEnemyAdvanced = false
  if gBattleEngine ~= nil and gBattleEngine.mEnemyPtr ~= nil and
      gBattleEngine.mEnemyPtr.mName ~= nil then
    postPlayEnemyAdvanced =
      gBattleEngine.mEnemyPtr.mName ~= "Trojan Spearman"
  end
  local postPlayHandoff = gAutomationSawPlayTutorial and
    postPlayEnemyAdvanced and snapshot ~= fixedPlayBoard and
    complete and anySelectable and settled
  local livePlayerStunned = false
  local livePlayerFrozen = false
  local livePlayerPetrified = false
  local livePlayerHealth = -1
  local livePlayerMaxHealth = -1
  local liveHealthPotionAvailable = false
  local livePurifyPotionAvailable = false
  if gBattleEngine ~= nil and gBattleEngine.mPlayerPtr ~= nil then
    local livePlayer = gBattleEngine.mPlayerPtr
    if livePlayer.mHealth ~= nil then livePlayerHealth = livePlayer.mHealth end
    if livePlayer.mMaxHealth ~= nil then livePlayerMaxHealth = livePlayer.mMaxHealth end
    if livePlayer.HasHealthPotion ~= nil then
      liveHealthPotionAvailable = livePlayer:HasHealthPotion()
    end
    if livePlayer.HasPurifyPotion ~= nil then
      livePurifyPotionAvailable = livePlayer:HasPurifyPotion()
    end
    if livePlayer.mPAM ~= nil and livePlayer.mPAM.mPlayingFrame ~= nil then
      local frame = livePlayer.mPAM.mPlayingFrame
      livePlayerStunned = frame == "stunned" or frame == "stunnedflinch"
      livePlayerPetrified = frame == "petrify1" or frame == "petrify2"
    end
  end
  -- Freeze does not use the player PAM frames used by stun and petrify.
  -- Ask BattleEngine's native overlay predicates so all incapacitations are
  -- reported from the same state MouseUp uses to accept the card click.
  if gBattleEngine ~= nil then
    if gBattleEngine.GridOverlayIsStun ~= nil then
      local nativeStun = gBattleEngine.GridOverlayIsStun(gBattleEngine)
      livePlayerStunned = livePlayerStunned or nativeStun == 1
    end
    if gBattleEngine.GridOverlayIsFreeze ~= nil then
      local nativeFreeze = gBattleEngine.GridOverlayIsFreeze(gBattleEngine)
      livePlayerFrozen = nativeFreeze == 1
    end
    if gBattleEngine.GridOverlayIsPetrify ~= nil then
      local nativePetrify = gBattleEngine.GridOverlayIsPetrify(gBattleEngine)
      livePlayerPetrified = livePlayerPetrified or nativePetrify == 1
    end
    -- GridOverlayIsFreeze can drop to zero while the modal animator remains
    -- on frozenloop. BattleEngine telemetry uses the animator frame because
    -- that is the actual click owner; keep TileEngine on the same definition
    -- so the shared edge global cannot oscillate on every update.
    if gBattleEngine.mGridOverlayPAM ~= nil and
        gBattleEngine.mGridOverlayPAM.mPlayingFrame ~= nil then
      local overlayFrame = tostring(
        gBattleEngine.mGridOverlayPAM.mPlayingFrame
      )
      livePlayerFrozen = livePlayerFrozen or overlayFrame == "frozen" or
        overlayFrame == "frozenloop" or overlayFrame == "breakfrozen"
    end
  end
  if gAutomationLivePlayerStunned == nil then
    gAutomationLivePlayerStunned = false
  end
  if livePlayerStunned ~= gAutomationLivePlayerStunned then
    gAutomationLivePlayerStunned = livePlayerStunned
    print("AUTOMATION_PLAYER_STUNNED=" ..
      (livePlayerStunned and "1" or "0") .. "|" ..
      livePlayerHealth .. "|" .. livePlayerMaxHealth .. "|" ..
      (liveHealthPotionAvailable and "1" or "0") .. "|" ..
      (livePurifyPotionAvailable and "1" or "0") .. "|E")
  end
  if gAutomationLivePlayerPetrified == nil then
    gAutomationLivePlayerPetrified = false
  end
  if livePlayerPetrified ~= gAutomationLivePlayerPetrified then
    gAutomationLivePlayerPetrified = livePlayerPetrified
    print("AUTOMATION_PLAYER_PETRIFIED=" ..
      (livePlayerPetrified and "1" or "0") .. "|" ..
      livePlayerHealth .. "|" .. livePlayerMaxHealth .. "|" ..
      (liveHealthPotionAvailable and "1" or "0") .. "|" ..
      (livePurifyPotionAvailable and "1" or "0") .. "|E")
  end
  if gAutomationLivePlayerFrozen == nil then
    gAutomationLivePlayerFrozen = false
  end
  if livePlayerFrozen ~= gAutomationLivePlayerFrozen then
    gAutomationLivePlayerFrozen = livePlayerFrozen
    print("AUTOMATION_PLAYER_FROZEN=" ..
      (livePlayerFrozen and "1" or "0") .. "|" ..
      livePlayerHealth .. "|" .. livePlayerMaxHealth .. "|" ..
      (liveHealthPotionAvailable and "1" or "0") .. "|" ..
      (livePurifyPotionAvailable and "1" or "0") .. "|E")
  end
  local incapOverlayKind = "none"
  local incapOverlayFrame = "none"
  if gBattleEngine ~= nil and gBattleEngine.mGridOverlayPAM ~= nil then
    local gridOverlay = gBattleEngine.mGridOverlayPAM
    if gridOverlay.mPlayingFrame ~= nil then
      incapOverlayFrame = tostring(gridOverlay.mPlayingFrame)
    end
    if livePlayerStunned then
      incapOverlayKind = "stunned"
    elseif livePlayerFrozen then
      incapOverlayKind = "frozen"
    elseif livePlayerPetrified then
      incapOverlayKind = "petrified"
    end
  end
  local incapOverlayState = incapOverlayKind .. "|" .. incapOverlayFrame ..
    "|" .. livePlayerHealth .. "|" .. livePlayerMaxHealth .. "|" ..
    (liveHealthPotionAvailable and "1" or "0") .. "|" ..
    (livePurifyPotionAvailable and "1" or "0")
  if gAutomationIncapOverlayState ~= incapOverlayState then
    gAutomationIncapOverlayState = incapOverlayState
    if incapOverlayKind ~= "none" then
      print("AUTOMATION_INCAP_OVERLAY=" .. incapOverlayState .. "|E")
    end
  end
  -- READY must describe the complete actionable state, not just its letters.
  -- Enemies can grey/smash tiles or change potion/health state while leaving
  -- the rack text untouched. Treat those mutations as a new stability epoch.
  local stabilitySnapshot = snapshot
  for y = 0, gTilesHigh - 1 do
    stabilitySnapshot = stabilitySnapshot .. "|" .. selectableRows[y] ..
      "|" .. zeroDamageRows[y] .. "|" .. powerRows[y]
  end
  stabilitySnapshot = stabilitySnapshot .. "|" .. livePlayerHealth ..
    "|" .. livePlayerMaxHealth .. "|" ..
    (liveHealthPotionAvailable and "1" or "0") .. "|" ..
    (livePlayerStunned and "1" or "0") .. "|" ..
    (livePlayerFrozen and "1" or "0") .. "|" ..
    (livePlayerPetrified and "1" or "0")
  if complete and settled and not interrupted and
      gAutomationStableSnapshot == stabilitySnapshot then
    if gAutomationStableTicks == nil then gAutomationStableTicks = 0 end
    gAutomationStableTicks = gAutomationStableTicks + 1
  else
    gAutomationStableSnapshot = stabilitySnapshot
    gAutomationStableTicks = 0
  end
  -- Require a short run of identical, motionless frames. Some enemy/level-up
  -- transitions briefly expose CanSelect between animation phases, which can
  -- otherwise publish coordinates for a board that is about to move.
  local ready = (complete and anySelectable and settled and not interrupted and
    gAutomationStableTicks >= 12) or postPlayHandoff

  if complete and ready and not gAutomationWasReady then
    local book = -1
    local chapter = -1
    local stage = -1
    local enemyName = "unknown"
    local health = -1
    local maxHealth = -1
    local playerHealth = -1
    local playerMaxHealth = -1
    local playerStunned = false
    local playerFrozen = false
    local playerPetrified = false
    local healthPotionAvailable = false
    local attackPotionAvailable = false
    local playerHasDamageOverTime = false
    local offense = 0
    local treasures = "none"
    local overkillThresholds = "none"
    if gBattleEngine ~= nil then
      if gBattleEngine.mBookNum ~= nil then book = gBattleEngine.mBookNum end
      if gBattleEngine.mStageNum ~= nil then stage = gBattleEngine.mStageNum end
      if gBattleEngine.mEnemyPtr ~= nil then
        local enemy = gBattleEngine.mEnemyPtr
        if enemy.mName ~= nil then enemyName = enemy.mName end
        if enemy.mHealth ~= nil then health = enemy.mHealth end
        if enemy.mMaxHealth ~= nil then maxHealth = enemy.mMaxHealth end
      end
      if gBattleEngine.mPlayerPtr ~= nil then
        local player = gBattleEngine.mPlayerPtr
        if player.mHealth ~= nil then playerHealth = player.mHealth end
        if player.mMaxHealth ~= nil then playerMaxHealth = player.mMaxHealth end
        if player.mOffenseBonusPct ~= nil then offense = player.mOffenseBonusPct end
        if player.mPAM ~= nil and player.mPAM.mPlayingFrame ~= nil then
          local frame = player.mPAM.mPlayingFrame
          playerStunned = frame == "stunned" or frame == "stunnedflinch"
          playerPetrified = frame == "petrify1" or frame == "petrify2"
        end
        playerFrozen = livePlayerFrozen
        if player.HasHealthPotion ~= nil then
          healthPotionAvailable = player:HasHealthPotion()
        end
        if player.HasAttackPotion ~= nil then
          attackPotionAvailable = player:HasAttackPotion()
        end
        if player.mStatusEffects ~= nil then
          for _, effect in pairs(player.mStatusEffects) do
            if type(effect) == "table" then
              local className = effect.mClassName
              local pamName = effect.mEffectPAMName
              if className == "FireAilment" or className == "PoisonAilment" or
                  pamName == "burning" or pamName == "poison" then
                playerHasDamageOverTime = true
              end
            end
          end
        end
        if player.mTreasures ~= nil then
          treasures = ""
          for treasureKey, treasureValue in pairs(player.mTreasures) do
            local treasure = treasureValue
            if type(treasure) ~= "table" and type(treasureKey) == "table" then
              treasure = treasureKey
            end
            if type(treasure) == "table" and treasure.mEnabled then
              local name = treasure.mName
              if name == nil then name = "unknown" end
              if treasures ~= "" then treasures = treasures .. "," end
              treasures = treasures .. name
            end
          end
          if treasures == "" then treasures = "none" end
        end
      end
    end
    if gBookManager ~= nil and gBookManager.mSelectedBook ~= nil then
      local selectedBook = gBookManager.mSelectedBook
      if selectedBook.mChapterNumber ~= nil then
        chapter = selectedBook.mChapterNumber
      end
    end
    local gemsAllowed = false
    if profile ~= nil then
      -- profile.Get is a native dot-style binding, not an object method. The
      -- game's own Lex:HandleOverkill passes exactly one argument.
      gemsAllowed = profile.Get("AllowGems")
    end
    if gemsAllowed and OVERKILL_TABLE ~= nil then
      overkillThresholds = ""
      for _, overkillEntry in pairs(OVERKILL_TABLE) do
        if type(overkillEntry) == "table" and overkillEntry[0] ~= nil then
          if overkillThresholds ~= "" then
            overkillThresholds = overkillThresholds .. ","
          end
          overkillThresholds = overkillThresholds .. overkillEntry[0]
        end
      end
      if overkillThresholds == "" then overkillThresholds = "none" end
    end
    if gAutomationSequence == nil then gAutomationSequence = 0 end
    gAutomationSequence = gAutomationSequence + 1
    -- The interactive PopCap console overwrites its first three writes while
    -- erasing the prompt. Sacrifice explicit sync records so real telemetry
    -- begins only after the console is stable.
    print("AUTOMATION_SYNC=1")
    print("AUTOMATION_SYNC=2")
    print("AUTOMATION_SYNC=3")
    for row = 0, gTilesHigh - 1 do
      print("AUTOMATION_LETTERS=" .. gAutomationSequence .. "|" .. row .. "|" ..
        letterRows[row] .. "|E")
      print("AUTOMATION_GEMS=" .. gAutomationSequence .. "|" .. row .. "|" ..
        gemRows[row] .. "|E")
      print("AUTOMATION_POWERS=" .. gAutomationSequence .. "|" .. row .. "|" ..
        powerRows[row] .. "|E")
      print("AUTOMATION_SELECTABLE=" .. gAutomationSequence .. "|" .. row .. "|" ..
        selectableRows[row] .. "|E")
      print("AUTOMATION_ZERO_DAMAGE=" .. gAutomationSequence .. "|" .. row .. "|" ..
        zeroDamageRows[row] .. "|E")
    end
    print("AUTOMATION_MODS=" .. gAutomationSequence .. "|" .. treasures .. "|E")
    print("AUTOMATION_OVERKILL=" .. gAutomationSequence .. "|" ..
      overkillThresholds .. "|E")
    -- Emit combat fields after the row batch. PopCap's interactive console
    -- redraws its prompt over the first few prints in a burst, but is stable by
    -- this point; the sequence ID still binds every record together.
    print("AUTOMATION_CONTEXT=" .. gAutomationSequence .. "|" .. book .. "|" ..
      chapter .. "|" .. stage .. "|E")
    print("AUTOMATION_ENEMY=" .. gAutomationSequence .. "|" .. enemyName .. "|E")
    print("AUTOMATION_HEALTH=" .. gAutomationSequence .. "|" .. health .. "|" ..
      maxHealth .. "|" .. offense .. "|E")
    print("AUTOMATION_PLAYER_HEALTH=" .. gAutomationSequence .. "|" ..
      playerHealth .. "|" .. playerMaxHealth .. "|E")
    print("AUTOMATION_PLAYER_STATUS=" .. gAutomationSequence .. "|" ..
      (playerStunned and "1" or "0") .. "|" ..
      (healthPotionAvailable and "1" or "0") .. "|" ..
      (playerHasDamageOverTime and "1" or "0") .. "|" ..
      (playerPetrified and "1" or "0") .. "|" ..
      (attackPotionAvailable and "1" or "0") .. "|" ..
      (playerFrozen and "1" or "0") .. "|E")
    print("AUTOMATION_RNG=" .. gAutomationSequence .. "|" ..
      (gAutomationRandomCalls or -1) .. "|E")
    print("AUTOMATION_READY_SEQ=" .. gAutomationSequence .. "|E")
    print("AUTOMATION_READY=" .. snapshot)
    if postPlayHandoff then gAutomationSawPlayTutorial = false end
  end
  gAutomationWasReady = complete and ready
end
