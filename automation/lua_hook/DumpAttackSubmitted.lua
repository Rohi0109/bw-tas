function BattleEngine:AutomationAttackSubmitted(word)
  local enemyName = "unknown"
  if self.mEnemyPtr ~= nil and self.mEnemyPtr.mName ~= nil then
    enemyName = self.mEnemyPtr.mName
  end
  -- IDs are monotonic within this Lua runtime, not across game restarts.
  gAutomationAttackId = (gAutomationAttackId or 0) + 1
  gAutomationAttackEnemy = self.mEnemyPtr
  gAutomationAttackHealth = nil
  if self.mEnemyPtr ~= nil then
    gAutomationAttackHealth = self.mEnemyPtr.mHealth
  end
  print("AUTOMATION_ATTACK_ID=" .. gAutomationAttackId .. "|" ..
    enemyName .. "|" .. tostring(word) .. "|E")
  print("AUTOMATION_ATTACK_SUBMITTED=" .. enemyName .. "|E")
  -- Read the selected tiles BEFORE SubmitTiles can refill/mutate them.
  -- GetFullWordValue is the native pure calculation: ApplyBonus receives the
  -- word's base damage, not the intrinsic value of each letter.
  if gTileEngine ~= nil and gTileTable ~= nil and gBoard ~= nil and
      gDamageByWordLength ~= nil and gTileEngine.GetFullWordValue ~= nil then
    local tiles = {}
    local slots = ""
    for y = 0, gTilesHigh - 1 do
      for x = 0, gTilesWide - 1 do
        local key = gBoard.GridGetTile(gBoard, x, y)
        local tile = gTileTable[key]
        if tile ~= nil and tile.mCObj ~= nil and
            tile.mCObj.IsSelected ~= nil and
            tile.mCObj.IsSelected(tile.mCObj) then
          table.insert(tiles, tile)
          if slots ~= "" then slots = slots .. "," end
          slots = slots .. (y * gTilesWide + x)
        end
      end
    end
    if slots ~= "" then
      local value = gTileEngine.GetWordValue(gTileEngine, tiles)
      local tier = math.round(value)
      if tier > 16 then tier = 16 end
      local base = 0
      if tier > 0 then base = gDamageByWordLength[tier - 1] end
      local full = gTileEngine.GetFullWordValue(gTileEngine, tiles)
      local offense = 0
      if self.mPlayerPtr ~= nil then
        offense = self.mPlayerPtr.mOffenseBonusPct or 0
      end
      print("AUTOMATION_DAMAGE_TRACE=" .. gAutomationAttackId .. "|" ..
        value .. "|" .. tier .. "|" .. tostring(base) .. "|" ..
        tostring(full) .. "|" .. offense .. "|" .. slots .. "|E")
      local damageTable = ""
      for index = 0, 15 do
        if damageTable ~= "" then damageTable = damageTable .. "," end
        damageTable = damageTable .. tostring(gDamageByWordLength[index])
      end
      if damageTable ~= gAutomationDamageTable then
        gAutomationDamageTable = damageTable
        print("AUTOMATION_DAMAGE_TABLE=" .. gAutomationAttackId .. "|" ..
          damageTable .. "|E")
      end
    end
  end
  gAutomationSubmittedWord = word
  gAutomationNativeValuePending = true
end
