function BookManager:AutomationDumpChapterMap()
  local selected = -1
  local selectedChapter = self:GetSelectedChapter()
  if selectedChapter ~= nil and selectedChapter.mChapterNumber ~= nil then
    selected = selectedChapter.mChapterNumber
  end
  local chapter = self:GetChapterNum()
  local book, currentChapter = self:GetCurrentBookAndChapterNum()
  -- Persist the last real map context for TreasureScreen. A fresh TAS runner
  -- may attach after combat, when no board snapshot exists in this lua.log.
  gAutomationChapterBook = book
  gAutomationChapterCurrent = currentChapter
  gAutomationChapterSelected = selected
  local canContinue = self:CanClickContinue()
  local signature = tostring(book) .. "|" .. tostring(currentChapter) .. "|" ..
    tostring(chapter) .. "|" .. tostring(selected) .. "|" ..
    tostring(canContinue)
  if gAutomationLastChapterMap ~= signature then
    gAutomationLastChapterMap = signature
    print("AUTOMATION_SYNC=1")
    print("AUTOMATION_SYNC=2")
    print("AUTOMATION_SYNC=3")
    print("AUTOMATION_CHAPTER_MAP=" .. signature .. "|E")
  end
end
