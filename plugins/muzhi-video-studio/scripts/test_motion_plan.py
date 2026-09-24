import copy,hashlib,tempfile,unittest
from pathlib import Path
from motion_plan import validate

class RoutePlanTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.addCleanup(self.tmp.cleanup)
  (self.root/'script.txt').write_text('先比较条件',encoding='utf-8');(self.root/'design.md').write_text('本片采用统一风格',encoding='utf-8')
  self.plan={'source_script':'script.txt','source_sha256':hashlib.sha256((self.root/'script.txt').read_bytes()).hexdigest(),'style_intent':'统一纸张和人物语言','segments':[{'id':'s1','spoken_text':'先比较条件','audience_takeaway':'同口径比较','visual_route':'native_mg','reason':'需要看懂关系','visual_action':'两列条件逐项对齐','library_candidates':['list-reveal'],'requires_exact_information':False,'evidence':[],'reading_plan':'关键项落位后留阅读时间','handoff':'比较项变成下一镜证据标签'}]}
 def test_pre_before_design_is_allowed(self):self.assertTrue(validate(self.plan,self.root)['passed'])
 def test_no_early_fake_timestamps(self):self.assertNotIn('start',self.plan['segments'][0]);self.assertTrue(validate(self.plan,self.root)['passed'])
 def test_script_drift(self): (self.root/'script.txt').write_text('changed');self.assertFalse(validate(self.plan,self.root)['passed'])
 def test_outside_source(self):self.plan['source_script']='../outside';self.assertFalse(validate(self.plan,self.root)['passed'])
 def test_unknown_route(self):self.plan['segments'][0]['visual_route']='motion-library';self.assertFalse(validate(self.plan,self.root)['passed'])
 def test_exact_i2v_rejected(self):s=self.plan['segments'][0];s.update(visual_route='image_to_video',generation_action='翻书',requires_exact_information=True);self.assertFalse(validate(self.plan,self.root)['passed'])
 def test_pending_evidence_draft_not_blocked(self):self.plan['segments'][0]['requires_exact_information']=True;r=validate(self.plan,self.root);self.assertTrue(r['passed']);self.assertTrue(r['warnings'])
 def test_storyboard_requires_design(self):self.assertFalse(validate(self.plan,self.root,'storyboard')['passed'])
 def test_storyboard_design_and_evidence(self):
  self.plan.update(design_source='design.md',design_sha256=hashlib.sha256((self.root/'design.md').read_bytes()).hexdigest());s=self.plan['segments'][0];s.update(requires_exact_information=True,evidence=[{'ref':'original.pdf p3','verified':True}]);self.assertTrue(validate(self.plan,self.root,'storyboard')['passed']);s['evidence'][0]['verified']=False;self.assertFalse(validate(self.plan,self.root,'storyboard')['passed'])
 def test_hybrid_needs_roles(self):s=self.plan['segments'][0];s.update(visual_route='hybrid',uses_image_to_video=True,generation_action='翻资料');self.assertFalse(validate(self.plan,self.root)['passed']);s['responsibilities']='人物让位，真实原文承载文字';self.assertTrue(validate(self.plan,self.root)['passed'])
 def test_hybrid_without_i2v_does_not_force_generation(self):s=self.plan['segments'][0];s.update(visual_route='hybrid',uses_image_to_video=False,responsibilities='真实证据放大后接本地条件对照');self.assertTrue(validate(self.plan,self.root)['passed'])
 def test_original_allowed_with_reason(self):s=self.plan['segments'][0];s['library_candidates']=[];self.assertFalse(validate(self.plan,self.root)['passed']);s['library_skip_reason']='全库没有合适的因果结构，本地原创';self.assertTrue(validate(self.plan,self.root)['passed'])
 def test_duplicate_ids(self):self.plan['segments'].append(copy.deepcopy(self.plan['segments'][0]));self.assertFalse(validate(self.plan,self.root)['passed'])

if __name__=='__main__':unittest.main()
