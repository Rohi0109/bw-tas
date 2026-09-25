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
  -- Prompt detection deliberately lives in Book:PromptToPlayMiniGame.  This
  -- map handler only knows a mini-game may be selected; its old chapter-based
  -- prediction could click before the native Yes/No panel existed.
end
