function TreasureScreen:AutomationClearTreasureScreen()
  -- The following story conversation may suspend every battle hook. Clear the
  -- treasure blocker while this widget is being destroyed so the runner may
  -- resume its safe conversation probes after the configured stall delay.
  if gAutomationLastDialog == "treasure" then
    gAutomationLastDialog = "none"
    gAutomationDialogTicks = 0
    if gAutomationDialogSequence == nil then gAutomationDialogSequence = 0 end
    gAutomationDialogSequence = gAutomationDialogSequence + 1
    print("AUTOMATION_SYNC=1")
    print("AUTOMATION_SYNC=2")
    print("AUTOMATION_SYNC=3")
    print("AUTOMATION_DIALOG=none|" ..
      gAutomationDialogSequence .. "|E")
  end
end
