function TreasureScreen:AutomationDumpTreasureScreen()
  -- Treasure selection is not dialogue. Emit an explicit blocker so the TAS
  -- never applies its safe-conversation fallback click to a treasure icon.
  if gAutomationLastDialog ~= "treasure" then
    gAutomationLastDialog = "treasure"
    gAutomationDialogTicks = 0
    if gAutomationDialogSequence == nil then gAutomationDialogSequence = 0 end
    gAutomationDialogSequence = gAutomationDialogSequence + 1
    print("AUTOMATION_SYNC=1")
    print("AUTOMATION_SYNC=2")
    print("AUTOMATION_SYNC=3")
    print("AUTOMATION_DIALOG=treasure|" ..
      gAutomationDialogSequence .. "|E")
  end
end
