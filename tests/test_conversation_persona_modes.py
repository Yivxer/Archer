"""Composer 人格菜单与 conversationPersona 辅助函数。"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

PERSONA_TS = Path("client/desktop/src/renderer/src/lib/conversationPersona.ts")


class TestConversationPersonaModule(unittest.TestCase):
    def test_exports_extended_mode_helper(self):
        source = PERSONA_TS.read_text(encoding="utf-8")
        self.assertIn("export function extendedConversationModes", source)
        self.assertIn("PRESET_MODE_IDS", source)

    def test_preset_block_lists_five_personas(self):
        source = PERSONA_TS.read_text(encoding="utf-8")
        block = source.split("export const PRESET_MODE_IDS", 1)[0]
        self.assertEqual(len(re.findall(r"\{ id: '", block)), 5)


class TestChatPagePersonaMenu(unittest.TestCase):
    def test_chat_page_exposes_full_mode_section(self):
        source = Path("client/desktop/src/renderer/src/pages/ChatPage.tsx").read_text(encoding="utf-8")
        self.assertIn("全部姿态", source)
        self.assertIn("extendedConversationModes", source)


if __name__ == "__main__":
    unittest.main()
