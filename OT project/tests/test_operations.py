"""Operational regressions: leave, interviews, collisions and honest partial plans."""
import copy
import unittest

from src.operations import audit, checked_instance, repair_timetable
from src.problem import Problem
from src.baseline.greedy_dsatur import greedy
from src.instance_generator import generate


def fixture():
    data = {
        'name':'Test college',
        'grid':{'days':['Mon','Tue','Wed'],'periods':['9 - 10','10 - 11','11 - 12','12 - 1'],'lunchPeriod':2},
        'groups':[{'id':'g1','name':'Class A','strength':20},{'id':'g2','name':'Class B','strength':20}],
        'faculty':[{'id':f'f{i}','name':f'Teacher {i}','maxWeekly':8,'maxDaily':3,'unavailable':[]} for i in (1,2)],
        'rooms':[{'id':'r1','name':'Room 1','capacity':30,'type':'classroom'}, {'id':'r2','name':'Room 2','capacity':30,'type':'classroom'}, {'id':'lab','name':'Lab','capacity':30,'type':'lab'}],
        'offerings':[{'id':'o1','subject':'Math','code':'M','groupIds':['g1'],'type':'theory','sessionsPerWeek':2,'eligibleFaculty':['f1','f2']},
                     {'id':'o2','subject':'Science','code':'S','groupIds':['g2'],'type':'theory','sessionsPerWeek':1,'eligibleFaculty':['f1','f2']}],
        'events':[{'id':'e1','offeringId':'o1','length':1,'headcount':20},{'id':'e2','offeringId':'o1','length':1,'headcount':20},{'id':'e3','offeringId':'o2','length':1,'headcount':20}],
    }
    sol = {'id':'test','objectives':{'f1':0,'f2':0,'f3':0},'onFront':True,'facultyOf':{'o1':'f1','o2':'f2'},
           'assignments':[{'eventId':'e1','day':0,'period':0,'roomId':'r1'}, {'eventId':'e2','day':1,'period':0,'roomId':'r1'}, {'eventId':'e3','day':0,'period':1,'roomId':'r2'}]}
    return data, sol


class OperationsTests(unittest.TestCase):
    def test_clean_audit_and_noop_keep_all_placements(self):
        data, sol = fixture()
        self.assertTrue(audit(data, sol)['valid'])
        plan = repair_timetable(data,sol,[],[])
        self.assertTrue(plan['audit']['valid'])
        self.assertEqual(plan['changes'],[])
        self.assertEqual(len(plan['solution']['assignments']),3)

    def test_leave_uses_eligible_substitute_for_only_affected_event(self):
        data, sol = fixture()
        before = copy.deepcopy((data, sol))
        plan = repair_timetable(data,sol,[{'facultyId':'f1','slots':[0]}],[])
        a = {a['eventId']:a for a in plan['solution']['assignments']}
        self.assertEqual((a['e1']['day'],a['e1']['period'],a['e1']['facultyId']),(0,0,'f2'))
        self.assertEqual(a['e2']['facultyId'],'f1')
        self.assertEqual(plan['changes'][0]['action'],'substituted')
        self.assertTrue(plan['audit']['valid'])
        self.assertEqual((data,sol),before)

    def test_no_substitute_reschedules_instead(self):
        data, sol = fixture()
        data['offerings'][0]['eligibleFaculty']=['f1']
        plan = repair_timetable(data,sol,[{'facultyId':'f1','slots':[0]}],[])
        a = next(a for a in plan['solution']['assignments'] if a['eventId']=='e1')
        self.assertNotEqual((a['day'],a['period']),(0,0))
        self.assertEqual(a['facultyId'],'f1')
        self.assertTrue(plan['audit']['valid'])

    def test_interview_blocks_students_and_moves_every_affected_lecture(self):
        data, sol = fixture()
        data['groups'][0]['unavailable']=[0,1,3]
        self.assertIn('group_unavailable',{i['code'] for i in audit(data,sol)['issues']})
        plan = repair_timetable(data,sol,[],[])
        for a in plan['solution']['assignments']:
            if a['eventId'] in ('e1','e2'):
                self.assertNotIn(a['day']*4+a['period'],[0,1,3])
        self.assertTrue(plan['audit']['valid'])

    def test_specific_cancellation_never_reinstates_same_occurrence(self):
        data, sol = fixture()
        plan = repair_timetable(data,sol,[],[{'eventId':'e1','reason':'Interview'}])
        a = next(a for a in plan['solution']['assignments'] if a['eventId']=='e1')
        self.assertNotEqual((a['day'],a['period']),(0,0))
        self.assertEqual(plan['changes'][0]['reason'],'Interview')
        self.assertTrue(plan['audit']['valid'])

    def test_fully_absent_students_produce_explicit_pending_not_collisions(self):
        data, sol = fixture()
        data['groups'][0]['unavailable']=list(range(12))
        plan = repair_timetable(data,sol,[],[])
        self.assertEqual({p['eventId'] for p in plan['pending']},{'e1','e2'})
        self.assertFalse(plan['audit']['valid'])
        self.assertFalse(plan['audit']['complete'])
        self.assertTrue(plan['audit']['collisionFree'])
        self.assertEqual(plan['audit']['issues'],[])
        self.assertEqual(plan['audit']['scheduledCount'],1)

    def test_zero_load_or_no_eligible_teacher_stays_pending(self):
        for mode in ('zero_load','no_teacher'):
            data, sol = fixture()
            if mode=='zero_load':
                for f in data['faculty']: f['maxWeekly']=0
            else:
                for o in data['offerings']: o['eligibleFaculty']=[]
            plan = repair_timetable(data,sol,[],[])
            self.assertEqual(len(plan['pending']),3)
            self.assertEqual(plan['solution']['assignments'],[])

    def test_audit_detects_all_three_collision_types_and_repair_clears_them(self):
        data, sol = fixture()
        sol['assignments'][2].update(day=0,period=0,roomId='r1',facultyId='f1')
        data['offerings'][1]['groupIds']=['g1']
        codes={i['code'] for i in audit(data,sol)['issues']}
        self.assertTrue({'teacher_clash','student_clash','room_clash'}<=codes)
        plan=repair_timetable(data,sol,[],[])
        self.assertTrue(plan['audit']['valid'])

    def test_load_limits_and_eligibility_checked_and_repaired(self):
        data, sol=fixture()
        data['faculty'][0]['maxWeekly']=1
        self.assertIn('weekly_overload',{i['code'] for i in audit(data,sol)['issues']})
        sol['assignments'][0]['facultyId']='missing'
        self.assertIn('ineligible_teacher',{i['code'] for i in audit(data,sol)['issues']})
        self.assertTrue(repair_timetable(data,sol,[],[])['audit']['valid'])

    def test_multi_period_lab_respects_full_interview_and_leave_duration(self):
        data, sol=fixture()
        data['offerings'][0]['type']='lab'
        for e in data['events'][:2]: e['length']=2
        for a in sol['assignments'][:2]: a['roomId']='lab'
        data['groups'][0]['unavailable']=[1]
        plan=repair_timetable(data,sol,[{'facultyId':'f1','slots':[5]}],[])
        self.assertTrue(plan['audit']['valid'])
        for a in plan['solution']['assignments']:
            if a['eventId'] in ('e1','e2'):
                self.assertNotIn(1,range(a['day']*4+a['period'],a['day']*4+a['period']+2))

    def test_invalid_times_duplicates_and_ids_rejected(self):
        for change in ('time','duplicate','unknown'):
            data, sol=fixture()
            if change=='time': sol['assignments'][0]['period']=-1
            if change=='duplicate': sol['assignments'].append(sol['assignments'][0].copy())
            if change=='unknown': sol['assignments'][0]['eventId']='unknown'
            self.assertFalse(audit(data,sol)['valid'])
            with self.assertRaises(ValueError): repair_timetable(data,sol,[],[])

    def test_invalid_availability_and_foreign_leaves_rejected(self):
        data, sol=fixture()
        data['faculty'][0]['unavailable']=[-1]
        with self.assertRaises(ValueError): checked_instance(data)
        data,sol=fixture()
        with self.assertRaises(ValueError): repair_timetable(data,sol,[{'facultyId':'unknown','slots':[0]}],[])
        with self.assertRaises(ValueError): repair_timetable(data,sol,[],[{'eventId':'unknown'}])

    def test_repeatable_repair_and_serialization(self):
        data,sol=fixture()
        data['groups'][0]['unavailable']=[0]
        a=repair_timetable(data,sol,[],[])
        self.assertEqual(a,repair_timetable(data,sol,[],[]))
        self.assertEqual(a['instance'],checked_instance(a['instance']).to_dict())
        self.assertTrue(audit(a['instance'],a['solution'])['valid'])

    def test_existing_solver_honors_student_unavailability(self):
        inst=generate('demo',1)
        inst.groups[0].unavailable=[0,1]
        prob=Problem(inst)
        sol=greedy(prob)
        self.assertEqual(sol.V,0)
        self.assertTrue(audit(inst.to_dict(),sol.to_dict(prob,'g',False))['valid'])

    def test_cpsat_honors_student_unavailability(self):
        from src.methods import run_method
        data, _ = fixture()
        data['groups'][0]['unavailable'] = [0, 1, 3]
        prob = Problem(checked_instance(data))
        result = run_method('cpsat', prob, 0, seed=0, cpsat_seconds=1)
        self.assertTrue(result.points)
        for point in result.points:
            self.assertTrue(audit(data, point.to_dict(prob,'exact',False))['valid'])


if __name__=='__main__':
    unittest.main()
