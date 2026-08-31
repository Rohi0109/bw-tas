function BookManager:AutomationDumpPreBattleDialogs()
  -- Opening chapter conversations exist before BattleEngine starts updating.
  -- Authorize only the globally owned convpanel here; BattleEngine takes over
  -- all interrupt, checkpoint, result, and level-up classification.
  if convpanel == nil or convpanel.Active == nil or not convpanel.Active() then
    return
  end
  if gAutomationDialogSequence == nil then gAutomationDialogSequence = 0 end
  if gAutomationDialogUpdates == nil then gAutomationDialogUpdates = 0 end
  if gAutomationDialogPulse == nil then gAutomationDialogPulse = 0 end
  if gAutomationDialogSource ~= "convpanel" then
    if gAutomationDialogSource ~= nil then
      print("AUTOMATION_DIALOG_INACTIVE=" .. gAutomationDialogSequence .. "|E")
    end
    gAutomationDialogSource = "convpanel"
    gAutomationDialogUpdates = 0
    gAutomationDialogPulse = 0
    gAutomationDialogSequence = gAutomationDialogSequence + 1
    print("AUTOMATION_DIALOG_ACTIVE=convpanel|" ..
      gAutomationDialogSequence .. "|E")
  end
  gAutomationDialogUpdates = gAutomationDialogUpdates + 1
  if gAutomationDialogUpdates >= 3 and ((gAutomationDialogUpdates - 3) % 15) == 0 then
    gAutomationDialogPulse = gAutomationDialogPulse + 1
    print("AUTOMATION_DIALOG_PULSE=convpanel|" ..
      gAutomationDialogSequence .. "|" .. gAutomationDialogPulse .. "|E")
  end
end
