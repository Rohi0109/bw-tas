TileEngine = {}

function TileEngine:AutomationDumpBoard()
  local snapshot = ""
  local gems = ""
  local powers = ""
  local letterRows = {}
  local gemRows = {}
  local powerRows = {}
  local complete = true
  local anySelectable = false
  local settled = true

  for y = 0, gTilesHigh - 1 do
    local letterRow = ""
    local gemRow = ""
    local powerRow = ""
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
        if powers ~= "" then powers = powers .. "," end
        powers = powers .. tilePower
        if powerRow ~= "" then powerRow = powerRow .. "," end
        powerRow = powerRow .. tilePower
        -- Use a normal table call instead of ':' so the appended method does
        -- not require PopCap's problematic SELF opcode.
        if not anySelectable and self.CanSelect(self, tileKey, x, y) then
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
  end

  if complete and snapshot ~= gAutomationLastBoard then
    gAutomationLastBoard = snapshot
    print("AUTOMATION_BOARD=" .. snapshot)
  end

  local interrupted = false
  if gBattleEngine ~= nil and gBattleEngine.mInterruptState then
    interrupted = true
  end
  if complete and settled and not interrupted and
      gAutomationStableSnapshot == snapshot then
    if gAutomationStableTicks == nil then gAutomationStableTicks = 0 end
    gAutomationStableTicks = gAutomationStableTicks + 1
  else
    gAutomationStableSnapshot = snapshot
    gAutomationStableTicks = 0
  end
  -- Require a short run of identical, motionless frames. Some enemy/level-up
  -- transitions briefly expose CanSelect between animation phases, which can
  -- otherwise publish coordinates for a board that is about to move.
  local ready = complete and anySelectable and settled and not interrupted and
    gAutomationStableTicks >= 12

  if complete and ready and not gAutomationWasReady then
    local book = -1
    local chapter = -1
    local stage = -1
    local enemyName = "unknown"
    local health = -1
    local maxHealth = -1
    local offense = 0
    local treasures = "none"
    local powerupPotions = 0
    local attackMultiplier = 1
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
        if player.mOffenseBonusPct ~= nil then offense = player.mOffenseBonusPct end
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
        if player.mItemSlots ~= nil and player.mItemSlots[1] ~= nil and
            player.mItemSlots[1].mNumActive ~= nil then
          powerupPotions = player.mItemSlots[1].mNumActive
        end
        if player.mStatusEffects ~= nil then
          for _, statusEffect in pairs(player.mStatusEffects) do
            if type(statusEffect) == "table" and
                statusEffect.mClassName == "DamageMultiplierEffect" and
                statusEffect.mOffensive and statusEffect.mMultiple ~= nil then
              attackMultiplier = statusEffect.mMultiple
            end
          end
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
    end
    print("AUTOMATION_MODS=" .. gAutomationSequence .. "|" .. treasures .. "|E")
    print("AUTOMATION_ITEMS=" .. gAutomationSequence .. "|" ..
      powerupPotions .. "|" .. attackMultiplier .. "|E")
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
    print("AUTOMATION_READY_SEQ=" .. gAutomationSequence .. "|E")
    print("AUTOMATION_READY=" .. snapshot)
  end
  gAutomationWasReady = complete and ready
end
