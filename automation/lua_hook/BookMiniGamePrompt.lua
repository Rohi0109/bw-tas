-- This is called from Book:PromptToPlayMiniGame immediately before the native
-- confirmation panel is created.  Unlike a chapter-map number, this edge
-- means that the Yes/No controls really are about to exist.
function Book:AutomationMiniGamePrompt()
  if gAutomationMiniGamePromptSequence == nil then
    gAutomationMiniGamePromptSequence = 0
  end
  gAutomationMiniGamePromptSequence = gAutomationMiniGamePromptSequence + 1

  local book = gAutomationChapterBook
  local chapter = gAutomationChapterCurrent
  if gBookManager ~= nil then
    book, chapter = gBookManager:GetCurrentBookAndChapterNum()
  end

  print("AUTOMATION_SYNC=1")
  print("AUTOMATION_SYNC=2")
  print("AUTOMATION_SYNC=3")
  print("AUTOMATION_MINIGAME_PROMPT=" .. tostring(book) .. "|" ..
    tostring(chapter) .. "|" ..
    tostring(gAutomationMiniGamePromptSequence) .. "|E")
end
