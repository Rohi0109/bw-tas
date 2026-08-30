function BookManager:AutomationChapterContinue()
  print("AUTOMATION_SYNC=1")
  print("AUTOMATION_SYNC=2")
  print("AUTOMATION_SYNC=3")
  print("AUTOMATION_CHAPTER_ACTION=continue|E")
  local selectedChapter = self:GetSelectedChapter()
  local bookChapter = nil
  if self.mSelectedBook ~= nil then
    bookChapter = self.mSelectedBook:GetSelectedChapter()
  end
  local managerMiniGame = selectedChapter ~= nil and selectedChapter.mIsMiniGame
  local bookMiniGame = bookChapter ~= nil and bookChapter.mIsMiniGame
  print("AUTOMATION_SYNC=1")
  print("AUTOMATION_SYNC=2")
  print("AUTOMATION_SYNC=3")
  print("AUTOMATION_CHAPTER_SELECTION=" ..
    tostring(managerMiniGame) .. "|" .. tostring(bookMiniGame) .. "|E")
  -- Moxie is offered at the observed checkpoint chapters. Yes always means
  -- skip the mini-game and continue the TAS route.
  local selected = gAutomationChapterSelected
  local moxiePrompt =
    selected == 4 or selected == 7 or selected == 9 or selected == 10
  if managerMiniGame or bookMiniGame or moxiePrompt then
    if gAutomationMiniGamePromptSequence == nil then
      gAutomationMiniGamePromptSequence = 0
    end
    gAutomationMiniGamePromptSequence =
      gAutomationMiniGamePromptSequence + 1
    print("AUTOMATION_SYNC=1")
    print("AUTOMATION_SYNC=2")
    print("AUTOMATION_SYNC=3")
    print("AUTOMATION_MINIGAME_PROMPT=" ..
      tostring(gAutomationChapterBook) .. "|" ..
      tostring(gAutomationChapterSelected) .. "|" ..
      tostring(gAutomationMiniGamePromptSequence) .. "|E")
  end
end
