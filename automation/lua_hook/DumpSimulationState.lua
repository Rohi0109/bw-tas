function BattleEngine:AutomationSimulationState()
  local id = tostring(gAutomationAttackId or 0)
  print("AUTOMATION_SIM_BEGIN=" .. id .. "|E")
  local owners = {player=self.mPlayerPtr, enemy=self.mEnemyPtr}
  for owner, creature in pairs(owners) do
    if creature ~= nil then
      local fields = {"mName", "mHealth", "mMaxHealth", "mDamageBuffer", "mState", "mOffenseBonusPct"}
      for _, field in ipairs(fields) do
        print("AUTOMATION_SIM_CREATURE=" .. id .. "|" .. owner .. "|" .. field .. "|" .. tostring(creature[field]) .. "|E")
      end
      if creature.mAttacks ~= nil then
        local count = 0
        for key, attack in pairs(creature.mAttacks) do
          if type(attack) == "table" then
            count = count + 1
            local fields = {"mMin", "mMax", "mRateCounter", "mDamage", "mState", "mAlreadyPerformed"}
            for _, field in ipairs(fields) do
              print("AUTOMATION_SIM_ATTACK=" .. id .. "|" .. owner .. "|" .. tostring(key) .. "|" .. field .. "|" .. tostring(attack[field]) .. "|E")
            end
          end
        end
        print("AUTOMATION_SIM_COLLECTION=" .. id .. "|" .. owner .. "|attacks|" .. tostring(count) .. "|E")
      else
        print("AUTOMATION_SIM_UNSUPPORTED=" .. id .. "|" .. owner .. "|attack-collection-missing|E")
      end
      if creature.mStatusEffects ~= nil then
        local count = 0
        for key, effect in pairs(creature.mStatusEffects) do
          if type(effect) == "table" then
            count = count + 1
            local fields = {"mClassName", "mBaseClass", "mDuration", "mNumTurns", "mDamage", "mDivisor", "mMinDamage", "mMultiple", "mOffensive", "mApplied", "mOnlyRemovableWhenUsed", "mStackDuration", "mRemoveInNumTurns", "mHasDoneEndTurn"}
            for _, field in ipairs(fields) do
              local value = effect[field]
              if type(value) ~= "table" and type(value) ~= "function" then
                print("AUTOMATION_SIM_EFFECT=" .. id .. "|" .. owner .. "|" .. tostring(key) .. "|" .. field .. "|" .. tostring(value) .. "|E")
              end
            end
            if effect.mQueue ~= nil then
              print("AUTOMATION_SIM_UNSUPPORTED=" .. id .. "|" .. owner .. "|effect-queue|E")
            end
          end
        end
        print("AUTOMATION_SIM_COLLECTION=" .. id .. "|" .. owner .. "|effects|" .. tostring(count) .. "|E")
      else
        print("AUTOMATION_SIM_UNSUPPORTED=" .. id .. "|" .. owner .. "|effect-collection-missing|E")
      end
    end
  end
  print("AUTOMATION_SIM_END=" .. id .. "|E")
end
