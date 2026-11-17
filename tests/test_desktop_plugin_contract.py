"""Real React stateful UI behavior against the plugin; mocked SDK transport boundary."""
from __future__ import annotations
import json
import shutil
import subprocess
from pathlib import Path
import pytest
REPO = Path(__file__).parents[1]
PLUGIN = REPO / 'key-manager/desktop/plugin.js'
HARNESS = REPO / 'tests/js/run_plugin.mjs'
pytestmark = pytest.mark.skipif(shutil.which('node') is None, reason='node required')
@pytest.fixture(scope='module')
def report():
    run = subprocess.run(['node','--no-warnings',str(HARNESS),str(PLUGIN)],capture_output=True,text=True,check=True,timeout=30)
    return json.loads(run.stdout)
def scenario(report,name):
    return next(s for s in report['scenarios'] if s['name']==name)
def mutations(s):
    return [c for c in s['calls'] if c.get('method') in {'session.model', 'config.set'} or (c['via']=='rest' and c['method']!='GET')]
def test_switch_is_owner_routed_and_only_accepted_selection_is_recorded(report):
    s=scenario(report,'accepted')
    rpc=next(c for c in s['calls'] if c.get('method')=='session.model')
    assert rpc['route']=={'connectionId':'local','mode':'local','profile':'default','targetProfile':'default'}
    assert rpc['params']=={'session_id':'chat-1','payload':{'model':'gemini-3.7-flash','provider':'custom:bonzai-key-landal'}}
    assert any(c.get('path')=='/sessions/stored-chat-1' and c['body']=={'slug':'landal'} for c in s['calls'])
    assert not any(c.get('path','').startswith('/sessions/') for c in scenario(report,'rejected')['calls'])
    assert any('Unknown model alias' in n['message'] for n in scenario(report,'rejected')['notices'])

def test_key_switch_keeps_chat_model(report):
    s = scenario(report, 'preserve-model')
    rpc = next(c for c in s['calls'] if c.get('method') == 'session.model')
    assert rpc['params']['payload'] == {'model': 'gpt-6.1-sol', 'provider': 'custom:bonzai-key-landal'}


def test_default_explicit_selection_is_advisory(report):
    s = scenario(report, 'default-selected')
    assert 'Selected · iO (Default)' in s['text']
    assert 'Active in chat' not in s['text']


def test_named_client_stays_selected_not_inactive(report):
    assert 'Selected · Landal' in scenario(report, 'named-client-status')['text']
    assert 'Inactive' not in scenario(report, 'named-client-status')['text']


def test_key_rows_do_not_imply_model_binding(report):
    assert 'legacy-model' not in scenario(report, 'key-model-hidden')['text']


def test_missing_chat_model_uses_prepared_default(report):
    s = scenario(report, 'no-current-model')
    assert next(c for c in s['calls'] if c.get('method') == 'session.model')['params']['payload']['model'] == 'gpt-6-luna'


def test_foreign_owner_cannot_mutate_even_using_retained_handler(report):
    assert mutations(scenario(report,'foreign-owner')) == []

def test_large_context_switch_requires_explicit_confirmation(report):
    required=scenario(report,'confirm-required')
    assert 'Large context input cost' in required['text']
    assert 'Switch' in required['text']
    assert not any(c.get('path','').startswith('/sessions/') for c in required['calls'])
    confirmed=scenario(report,'confirm-switch')
    picks=[c for c in confirmed['calls'] if c.get('method')=='session.model']
    assert len(picks)==2
    assert picks[1]['params']['confirm']=='confirmation-token'
    assert picks[1]['params']['payload'] == picks[0]['params']['payload']
    assert len([c for c in confirmed['calls'] if c.get('path') == '/credentials/landal/route']) == 1
    assert any(c.get('path','').startswith('/sessions/') for c in confirmed['calls'])
    for name in ('confirm-cancel','confirm-focus-race'):
        assert len([c for c in scenario(report,name)['calls'] if c.get('method')=='session.model'])==1
def test_save_and_use_does_not_activate_a_chat_focused_during_save(report):
    s=scenario(report,'save-focus-race')
    assert any(c.get('path')=='/credentials' and c['method']=='POST' for c in s['calls'])
    assert not any(c.get('method') in {'session.model', 'config.set'} for c in s['calls'])
def test_profile_change_clears_secret_state(report):
    inputs=scenario(report,'profile-secret-clear')['inputs']
    assert len(inputs)==2
    assert all(i['value']=='' for i in inputs)
    assert all(i['label'] for i in inputs)

def test_owner_info_not_advisory_selection_determines_status(report):
    assert 'Inactive' in scenario(report,'inactive')['text']
    assert 'Selected · Landal' in scenario(report,'unknown-key')['text']
    assert 'Active in chat' not in scenario(report,'unknown-key')['text']
    assert 'Selected · Landal' in scenario(report,'unknown-key')['text']
def test_deferred_switch_is_pending_not_confirmed_active(report):
    s=scenario(report,'deferred')
    assert 'Pending' in s['text']
    assert not any(n['kind']=='success' for n in s['notices'])
def test_events_reconcile_and_unmount_cleans_listeners(report):
    assert 'Inactive' in scenario(report,'event-reconcile')['text']
    assert scenario(report,'event-reconcile')['events'] > 0
    assert report['eventsAfterUnmount'] == 0

def test_existing_rename_and_test_use_profile_scoped_backend(report):
    s=scenario(report,'rename')
    assert any(c.get('method')=='PATCH' and c['body']=={'label':'Landal Updated'} for c in s['calls'])
    assert 'Landal Updated' in s['text']
    s=scenario(report,'test-stored')
    assert any(c.get('path')=='/credentials/test-stored' and c['body']=={'id':'landal'} for c in s['calls'])
def test_retained_rename_and_test_handlers_refuse_foreign_scope(report):
    assert mutations(scenario(report,'late-foreign-actions')) == []
    assert mutations(scenario(report,'retained-profile-use')) == []
    assert mutations(scenario(report,'retained-profile-save')) == []
def test_blocked_deletion_reports_backend_error_and_no_fallback_copy(report):
    s=scenario(report,'delete-blocked')
    assert any('409' in n['message'] for n in s['notices'])
    assert 'chats using it fall back to iO' not in s['text']
def test_palette_opens_registered_settings_page(report):
    assert report['settings']
    assert any(c['via']=='navigate' for c in scenario(report,'palette')['calls'])
    assert 'keys-page' in report['olderRoute']['registered']
    assert report['olderRoute']['calls']==[{'via':'navigate','path':'/bonzai-keys'}]

def test_focus_races_do_not_record_selection_or_retarget_rpc(report):
    assert not any(c.get('method') in {'session.model', 'config.set'} for c in scenario(report,'route-race')['calls'])
    assert not any(c.get('method') in {'session.model', 'config.set'} for c in scenario(report,'profile-route-race')['calls'])
    s=scenario(report,'rpc-race')
    assert [c['params']['session_id'] for c in s['calls'] if c.get('method') in {'session.model', 'config.set'}]==['chat-1']
    assert not any(c.get('path','').startswith('/sessions/') for c in s['calls'])
def test_busy_chat_refuses_key_switch_before_and_after_route_lookup(report):
    for name in ('busy-switch','busy-route-race'):
        s=scenario(report,name)
        assert not any(c.get('method') in {'session.model', 'config.set'} for c in s['calls'])
        assert any('Wait until' in n['message'] for n in s['notices'])
    assert mutations(scenario(report,'busy-save'))==[]
def test_accepted_idle_switch_clears_pending(report):
    assert 'Pending' not in scenario(report,'pending-clear')['text']
    assert scenario(report,'pending-clear')['storage']=={}
def test_pending_deletion_protection_survives_reload(report):
    assert not any(c.get('method')=='DELETE' for c in scenario(report,'pending-reload')['calls'])
def test_pending_delete_guard_does_not_cross_profiles(report):
    assert any(c.get('method')=='DELETE' for c in scenario(report,'pending-other-profile')['calls'])

def test_wrong_durable_session_info_is_rejected(report):
    assert 'Inactive' not in scenario(report,'stored-query-mismatch')['text']
    assert 'Inactive' not in scenario(report,'stored-event-mismatch')['text']

def test_background_owner_event_cannot_change_status(report):
    assert 'Inactive' not in scenario(report,'foreign-event')['text']
def test_pending_alias_cannot_be_removed_before_deferred_switch_settles(report):
    s=scenario(report,'pending-remove')
    assert not any(c.get('method')=='DELETE' for c in s['calls'])
    assert not any(c.get('path','').startswith('/sessions/') for c in s['calls'])
