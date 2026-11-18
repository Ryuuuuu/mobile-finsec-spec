from pathlib import Path
import tempfile
import unittest
from integration.skill_structure import load_skills,provider_context

class SkillStructureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for role in ('common','aos','ios'):
            path=self.root/'mock-item'/role/'SKILL.md';path.parent.mkdir(parents=True)
            path.write_text('MOCK STRUCTURE ONLY '+role,encoding='utf-8')
    def test_common_required_platform_selected(self):
        for platform,expected in ((None,['common']),('aos',['common','aos']),('ios',['common','ios'])):
            bundle=load_skills(self.root,'mock-item',platform)
            self.assertEqual([s['role'] for s in bundle['skills']],expected)
            self.assertTrue(all(len(s['sha256'])==64 for s in bundle['skills']))
    def test_snapshot_delivery_detached_and_opaque(self):
        bundle=load_skills(self.root,'mock-item','ios');context=provider_context(bundle)
        bundle['skills'][0]['content']='changed'
        self.assertEqual(context['skill_snapshot']['skills'][0]['content'],'MOCK STRUCTURE ONLY common')
    def test_missing_required_or_selected_rejected(self):
        (self.root/'mock-item'/'ios'/'SKILL.md').unlink()
        with self.assertRaises(FileNotFoundError):load_skills(self.root,'mock-item','ios')
        self.assertEqual(len(load_skills(self.root,'mock-item','aos')['skills']),2)
        (self.root/'mock-item'/'common'/'SKILL.md').unlink()
        with self.assertRaises(FileNotFoundError):load_skills(self.root,'mock-item','aos')
    def test_invalid_paths_platform_and_size(self):
        with self.assertRaises(ValueError):load_skills(self.root,'../escape')
        with self.assertRaises(ValueError):load_skills(self.root,'mock-item','other')
        path=self.root/'mock-item'/'common'/'SKILL.md';path.write_bytes(b'x'*65537)
        with self.assertRaises(ValueError):load_skills(self.root,'mock-item')
        path.write_text(' ',encoding='utf-8')
        with self.assertRaises(ValueError):load_skills(self.root,'mock-item')
