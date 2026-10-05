"""Read-only pre-director route audit; semantic v1 is explicit opt-in only."""
from pathlib import Path
import argparse, hashlib, json, math, re

ROUTES={'image_to_video','native_mg','official_evidence','sourced_chart','vox_layered_broll','real_media','hybrid'}
LIBRARY_ROUTES={'native_mg','official_evidence','sourced_chart','vox_layered_broll'}
GUARD_KINDS={'condition','negation','number','attribution'}
RESOURCE_SOURCES={'original','shotcraft','other_library','agent_motion','evidence'}


def _candidate_provenance(option, chosen_id, errors, label):
    """Verify declared external options against the current indexed source bytes."""
    from resource_handoff import candidate_identity

    rid = option['resource_id']
    try:
        identity = candidate_identity(rid)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        errors.append(f'{label}: unknown or unavailable candidate ID {rid}: {exc}')
        return
    source = option['source']
    if ((source == 'shotcraft' and identity['source'] != 'shotcraft') or
        (source == 'agent_motion' and identity['source'] != 'agent_motion') or
        (source == 'other_library' and identity['source'] in ('shotcraft', 'agent_motion'))):
        errors.append(f'{label}: candidate ID source does not match declared source')
    receipt = option.get('source_provenance')
    if not isinstance(receipt, dict):
        errors.append(f'{label}: source_provenance required for declared library candidate')
        return
    state = identity['source_state']
    reading = receipt.get('reading_status')
    usage = receipt.get('usage_kind')
    if usage not in ('reference_only', 'planned_adaptation', 'planned_backend'):
        errors.append(f'{label}: usage_kind must distinguish reference, adaptation, or planned backend')
    if rid == chosen_id and usage == 'reference_only':
        errors.append(f'{label}: chosen library source needs a planned adaptation or backend, not reference_only')
    if source == 'shotcraft' and usage == 'planned_backend':
        errors.append(f'{label}: Shotcraft text card is not an executable backend')
    if state == 'drift':
        errors.append(f'{label}: indexed source SHA-256 differs from current original')
    elif state == 'missing':
        if reading != 'missing' or receipt.get('source_sha256') is not None:
            errors.append(f'{label}: missing original must be marked missing without a read claim')
        if rid == chosen_id:
            errors.append(f'{label}: missing original cannot be chosen')
    else:
        if reading not in ('read', 'not_read'):
            errors.append(f'{label}: reading_status must be read or not_read')
        if receipt.get('source_sha256') != identity['current_sha256']:
            errors.append(f'{label}: source_provenance SHA-256 differs from current original')
        if reading == 'read' and receipt.get('read_scope') != 'complete_text':
            errors.append(f'{label}: read claim requires bounded complete_text read_scope')
        if rid == chosen_id and reading != 'read':
            errors.append(f'{label}: chosen library candidate requires current original read receipt')


def _search_and_selection(segment, plan, root, errors, warnings, label):
    """Re-run the original library search and check the recorded choice boundary."""
    from resource_handoff import search_receipt, verify_preview

    searches = segment.get('library_searches')
    if not isinstance(searches, list) or not searches or len(searches) > 6:
        errors.append(f'{label}: library_searches needs one to six current search receipts')
        return
    result_ids = set()
    valid_search = False
    verified_historical_binding = None
    for index, receipt in enumerate(searches, 1):
        prefix = f'{label} library_searches {index}'
        if not isinstance(receipt, dict):
            errors.append(f'{prefix}: structured search receipt required')
            continue
        try:
            expected = search_receipt(receipt.get('terms'), receipt.get('role'), receipt.get('per_source'))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            errors.append(f'{prefix}: invalid current search: {exc}')
            continue
        if receipt != expected:
            same_results = (set(receipt) == set(expected) and
                            all(receipt.get(key) == expected[key] for key in ('terms', 'role', 'per_source', 'results')))
            binding = segment.get('preview_binding')
            has_media = isinstance(binding, dict) and isinstance(binding.get('preview_media'), dict)
            if same_results and has_media and receipt.get('index_digest_sha256') != expected['index_digest_sha256']:
                if verified_historical_binding is None:
                    try:
                        verified_historical_binding = verify_preview(root, plan, segment.get('id'))['passed'] is True
                    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError):
                        verified_historical_binding = False
                if verified_historical_binding:
                    warnings.append(f'{prefix}: matched index file digest changed while exact result IDs/source SHA stayed stable; '
                                    'existing bound media and segment core verified; historical choice only, re-search for a new plan')
                else:
                    errors.append(f'{prefix}: index digest drift cannot use unverified or changed preview binding')
                    continue
            else:
                errors.append(f'{prefix}: query, index identity, or result ID/SHA differs from current search')
                continue
        valid_search = True
        result_ids.update(row['id'] for row in expected['results'])
    if not valid_search:
        return
    candidates = segment.get('library_candidates')
    if not isinstance(candidates, list):
        return
    if any(not isinstance(candidate, str) for candidate in candidates):
        return
    if len(candidates) != len(set(candidates)):
        errors.append(f'{label}: duplicate library_candidates')
    if not set(candidates).issubset(result_ids):
        errors.append(f'{label}: library_candidates must come from current search result IDs')
    decisions = segment.get('library_decisions')
    if not isinstance(decisions, list):
        errors.append(f'{label}: library_decisions must record selected/rejected candidates')
        return
    chosen = segment.get('chosen_resource')
    chosen_id = chosen.get('resource_id') if isinstance(chosen, dict) else None
    decision_ids = []
    for index, decision in enumerate(decisions, 1):
        prefix = f'{label} library_decisions {index}'
        if not isinstance(decision, dict):
            errors.append(f'{prefix}: structured decision required')
            continue
        rid, status, reason = (decision.get(key) for key in ('resource_id', 'decision', 'reason'))
        if not isinstance(rid, str) or rid not in result_ids:
            errors.append(f'{prefix}: resource_id must be a current search result')
            continue
        if status not in ('selected', 'rejected') or not isinstance(reason, str) or not reason.strip():
            errors.append(f'{prefix}: selected/rejected and a concrete reason required')
        if status == 'selected' and rid != chosen_id:
            errors.append(f'{prefix}: selected library ID must be the chosen_resource')
        if status == 'rejected' and rid == chosen_id:
            errors.append(f'{prefix}: chosen_resource cannot be rejected')
        decision_ids.append(rid)
    if len(decision_ids) != len(set(decision_ids)):
        errors.append(f'{label}: duplicate library_decisions resource_id')
    if not set(candidates).issubset(decision_ids):
        errors.append(f'{label}: every library_candidates ID needs a selection decision')
    if chosen_id in result_ids and chosen_id not in decision_ids:
        errors.append(f'{label}: chosen library resource needs a selected decision')
    if not candidates:
        skip = segment.get('library_skip_reason')
        if not isinstance(skip, str) or not skip.strip():
            errors.append(f'{label}: library_skip_reason required after a search')
        if result_ids and not any(isinstance(d, dict) and d.get('decision') == 'rejected' for d in decisions):
            errors.append(f'{label}: nonzero search with no library candidate needs a rejected result and reason')

def _local(root, value):
    if not isinstance(value,str) or not value.strip():
        raise ValueError('source path must be a non-empty project-relative path')
    rel=Path(value)
    if rel.is_absolute() or '..' in rel.parts:
        raise ValueError('source path must stay inside project')
    path=(root/rel).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('source symlink escapes project')
    return path

def _semantic_audit(plan, root, segments, errors, stage):
    """Check a human-authored semantic contract, not the truth of its interpretation."""
    # Imported here because the bridge imports this module for its existing route audit.
    from agent_motion_bridge import BridgeError, SRT_TIMECODE, milliseconds, srt_cues
    from expression_contract import validate_segment, validate_visual_decision
    from project_policy import requires_visual_decision

    def nonempty(value):
        return isinstance(value, str) and bool(value.strip())

    def cue_ids(value, label, *, minimum=1):
        if not isinstance(value, list) or len(value) < minimum or any(
            type(cue) is not int or cue not in known_ids for cue in value
        ):
            errors.append(f'{label}: cue_ids must name existing SRT cues')
            return None
        if len(set(value)) != len(value) or value != sorted(value):
            errors.append(f'{label}: cue_ids must be unique and in SRT order')
            return None
        return value

    authored = plan.get('timebase_kind') == 'authored_screen_timing'
    known_ids = []
    cue_text = {}
    cue_times = {}
    if authored:
        if plan.get('srt_source') or plan.get('audio_source'):
            errors.append('authored_screen_timing: no real SRT or voice may be claimed in the silent study plan')
            return
        entries = plan.get('authored_cues')
        if not isinstance(entries, list) or not entries:
            errors.append('authored_screen_timing: nonempty authored_cues required')
            return
        try:
            source_text = _local(root, plan.get('source_script')).read_text(encoding='utf-8-sig')
        except (ValueError, OSError, UnicodeError) as exc:
            errors.append(f'authored_screen_timing source: {exc}')
            return
        previous_end = 0.0
        for entry in entries:
            if (not isinstance(entry, dict) or type(entry.get('id')) is not int or entry['id'] <= 0 or
                    not nonempty(entry.get('text')) or type(entry.get('start_seconds')) not in (int, float) or
                    type(entry.get('end_seconds')) not in (int, float)):
                errors.append('authored_cues: id, exact text and screen seconds required')
                return
            start, end = entry['start_seconds'], entry['end_seconds']
            if (not math.isfinite(start) or not math.isfinite(end) or start < previous_end - .001 or end <= start or
                    (known_ids and entry['id'] <= known_ids[-1]) or
                    ''.join(entry['text'].split()) not in ''.join(source_text.split())):
                errors.append('authored_cues: positive ordered nonoverlapping cues must quote this authored script')
                return
            known_ids.append(entry['id'])
            cue_text[entry['id']] = ''.join(entry['text'].split())
            cue_times[entry['id']] = (float(start), float(end))
            previous_end = float(end)
    else:
        try:
            srt_path = _local(root, plan.get('srt_source'))
            if not srt_path.is_file():
                raise OSError('SRT file missing')
            srt_bytes = srt_path.read_bytes()
            if plan.get('srt_sha256') != hashlib.sha256(srt_bytes).hexdigest():
                errors.append('srt_source: SRT hash drift or missing hash')
            srt_text = srt_bytes.decode('utf-8-sig')
            times = srt_cues(srt_text)
        except (ValueError, OSError, UnicodeError, BridgeError) as exc:
            errors.append(f'srt_source: {exc}')
            return
        blocks = [block for block in re.split(r'\r?\n\s*\r?\n', srt_text) if block.strip()]
        # Keep each real SRT index, rather than assuming position is the index.
        for block in blocks:
            lines = block.strip().splitlines()
            first = lines[0].strip()
            if not first.isdecimal():
                errors.append('srt_source: cue index is not numeric')
                return
            try:
                cue_id = int(first)
            except ValueError:
                errors.append('srt_source: cue index is too long or invalid')
                return
            known_ids.append(cue_id)
            cue_text[cue_id] = ''.join(line.strip() for line in lines[2:])
        if len(known_ids) != len(times) or any(cue <= 0 for cue in known_ids) or known_ids != sorted(set(known_ids)):
            errors.append('srt_source: cue indices must be positive, unique, and ordered')
            return
        cue_times = dict(zip(known_ids, times))
    known_ids = set(known_ids)
    decision_cue_times = cue_times if authored else {
        cue_id: (milliseconds(bounds[0]) / 1000, milliseconds(bounds[1]) / 1000)
        for cue_id, bounds in cue_times.items()
    }
    decision_required = plan.get('semantic_contract_version') == 2 and requires_visual_decision(root, plan)

    excluded = set()
    exclusions = plan.get('srt_exclusions')
    if not isinstance(exclusions, list):
        errors.append('srt_exclusions: must be a list (use [] when every cue is covered)')
    else:
        for i, item in enumerate(exclusions):
            label = f'srt_exclusions {i+1}'
            if not isinstance(item, dict) or type(item.get('cue_id')) is not int or item['cue_id'] not in known_ids or not nonempty(item.get('reason')):
                errors.append(f'{label}: needs existing cue_id and reason')
                continue
            if item['cue_id'] in excluded:
                errors.append(f'{label}: duplicate excluded cue')
            excluded.add(item['cue_id'])

    owners = {}
    segment_by_id = {}
    last_cue = None
    for i, segment in enumerate(segments):
        label = f'segment {i+1}'
        if not isinstance(segment, dict):
            continue
        sid = segment.get('id')
        if nonempty(sid):
            segment_by_id[sid] = (i, segment)
        ids = cue_ids(segment.get('srt_cue_ids'), f'{label} srt_cue_ids')
        if ids:
            for cue in ids:
                owners.setdefault(cue, []).append((sid if nonempty(sid) else None, i))
                if cue in excluded:
                    errors.append(f'{label}: cue {cue} is both covered and excluded')
                if last_cue is not None and cue < last_cue:
                    errors.append(f'{label}: SRT cue order moves backward')
                last_cue = cue
            clock_key = 'authored_timecode' if authored else 'srt_timecode'
            match = SRT_TIMECODE.fullmatch(str(segment.get(clock_key, '')).strip())
            if match is None:
                errors.append(f'{label}: {clock_key} must match the bound cue range')
            else:
                try:
                    actual = (milliseconds(match.group(1)), milliseconds(match.group(2)))
                    expected = ((round(cue_times[ids[0]][0] * 1000), round(cue_times[ids[-1]][1] * 1000)) if authored else
                                (milliseconds(cue_times[ids[0]][0]), milliseconds(cue_times[ids[-1]][1])))
                    if actual != expected:
                        errors.append(f'{label}: {clock_key} drifts from bound cues')
                except BridgeError as exc:
                    errors.append(f'{label}: invalid srt_timecode: {exc}')
        for key in ('semantic_role', 'original_intent', 'shot_purpose'):
            if not nonempty(segment.get(key)):
                errors.append(f'{label}: missing {key}')
        guards = segment.get('meaning_guards')
        if not isinstance(guards, list):
            errors.append(f'{label}: meaning_guards must be a list')
        else:
            for j, guard in enumerate(guards):
                prefix = f'{label} meaning_guards {j+1}'
                if not isinstance(guard, dict) or not isinstance(guard.get('kind'), str) or guard['kind'] not in GUARD_KINDS or not nonempty(guard.get('content')) or not nonempty(guard.get('preservation')):
                    errors.append(f'{prefix}: needs kind, content, and preservation')
                    continue
                guard_ids = cue_ids(guard.get('cue_ids'), prefix)
                if guard_ids and ids and not set(guard_ids).issubset(ids):
                    errors.append(f'{prefix}: guarded cues must stay in this segment')
                if guard_ids:
                    source_quote = ''.join(cue_text[cue] for cue in guard_ids)
                    if guard['content'].strip() not in source_quote:
                        errors.append(f'{prefix}: content must be an exact quote from bound SRT cues')
        parts = segment.get('cue_text_parts', [])
        if not isinstance(parts, list):
            errors.append(f'{label}: cue_text_parts must be a list')
        else:
            part_ids = []
            for part in parts:
                if not isinstance(part, dict) or type(part.get('cue_id')) is not int or not nonempty(part.get('text')) or not ids or part['cue_id'] not in ids:
                    errors.append(f'{label}: cue_text_parts must quote a cue in this segment')
                    continue
                part_ids.append(part['cue_id'])
                if part['text'].strip() not in cue_text[part['cue_id']]:
                    errors.append(f'{label}: cue_text_parts text is not in its SRT cue')
            if len(part_ids) != len(set(part_ids)):
                errors.append(f'{label}: duplicate cue_text_parts cue_id')
        options = segment.get('resource_options')
        option_ids = set()
        option_sources = {}
        if not isinstance(options, list) or not options:
            errors.append(f'{label}: resource_options must be a non-empty list')
        else:
            for j, option in enumerate(options):
                prefix = f'{label} resource_options {j+1}'
                if not isinstance(option, dict) or any(not nonempty(option.get(key)) for key in ('resource_id', 'source', 'reason')):
                    errors.append(f'{prefix}: needs resource_id, source, and reason')
                    continue
                if option['source'] not in RESOURCE_SOURCES:
                    errors.append(f'{prefix}: unknown source')
                    continue
                resource_id = option['resource_id']
                if plan.get('semantic_contract_version') == 2 and option['source'] in ('original', 'evidence'):
                    from resource_handoff import SOURCES
                    if ':' in resource_id and resource_id.split(':', 1)[0].casefold() in SOURCES:
                        errors.append(f'{prefix}: reserved library ID cannot be labeled {option["source"]}')
                if resource_id in option_ids:
                    errors.append(f'{prefix}: duplicate resource_id')
                option_ids.add(resource_id)
                option_sources[resource_id] = option['source']
                candidates = segment.get('library_candidates')
                cases = segment.get('reference_cases')
                evidence = segment.get('evidence')
                if option['source'] in ('shotcraft', 'other_library') and resource_id not in (candidates if isinstance(candidates, list) else []):
                    errors.append(f'{prefix}: library resource_id must be in library_candidates')
                if option['source'] == 'agent_motion':
                    case_ids = [case.get('case_id') for case in (cases if isinstance(cases, list) else []) if isinstance(case, dict)]
                    expected = ([case_id if case_id.startswith('agent_motion:') else 'agent_motion:' + case_id
                                 for case_id in case_ids if isinstance(case_id, str)]
                                if plan.get('semantic_contract_version') == 2 else case_ids)
                    if resource_id not in expected:
                        errors.append(f'{prefix}: Agent Motion resource_id must be in reference_cases')
                if option['source'] == 'evidence' and resource_id not in [e.get('ref') for e in (evidence if isinstance(evidence, list) else []) if isinstance(e, dict)]:
                    errors.append(f'{prefix}: evidence resource_id must be in evidence refs')
        chosen = segment.get('chosen_resource')
        if not isinstance(chosen, dict) or not nonempty(chosen.get('resource_id')) or not nonempty(chosen.get('reason')) or chosen.get('resource_id') not in option_ids:
            errors.append(f'{label}: chosen_resource needs a listed resource_id and reason')
        elif option_sources.get(chosen['resource_id']) == 'agent_motion' and segment.get('motion_backend') != 'agent_motion':
            errors.append(f'{label}: chosen Agent Motion resource requires motion_backend=agent_motion')
        if plan.get('semantic_contract_version') == 2 and isinstance(options, list):
            chosen_id = chosen.get('resource_id') if isinstance(chosen, dict) else None
            for j, option in enumerate(options, 1):
                if isinstance(option, dict) and option.get('source') in ('shotcraft', 'other_library', 'agent_motion') and nonempty(option.get('resource_id')):
                    _candidate_provenance(option, chosen_id, errors, f'{label} resource_options {j}')
        continuity = segment.get('continuity')
        next_id = segments[i+1].get('id') if i+1 < len(segments) and isinstance(segments[i+1], dict) else None
        if not isinstance(continuity, dict) or not nonempty(continuity.get('entry')) or not nonempty(continuity.get('exit')) or continuity.get('next_segment_id') != next_id:
            errors.append(f'{label}: continuity needs entry, exit, and the actual next_segment_id (null at end)')
        if plan.get('semantic_contract_version') == 2:
            validate_segment(segment, root, errors, label)
            if decision_required:
                validate_visual_decision(segment, decision_cue_times, errors, label, stage)

    missing = known_ids - set(owners) - excluded
    if missing:
        errors.append(f'SRT cues lack coverage or explicit exclusion: {sorted(missing)}')
    for cue, assigned in owners.items():
        if len(assigned) < 2:
            continue
        parts = []
        for sid, segment_index in assigned:
            segment = segments[segment_index]
            listed = segment.get('cue_text_parts')
            matches = [part for part in listed if isinstance(part, dict) and part.get('cue_id') == cue] if isinstance(listed, list) else []
            if len(matches) != 1 or not nonempty(matches[0].get('text')):
                errors.append(f'segment {segment_index+1}: shared cue {cue} needs one cue_text_parts exact-text slice')
                continue
            parts.append(matches[0]['text'].strip())
        if ''.join(parts) != cue_text[cue]:
            errors.append(f'cue {cue}: shared cue_text_parts do not reconstruct original SRT text in segment order')
    for i, segment in enumerate(segments):
        if not isinstance(segment, dict) or not isinstance(segment.get('srt_cue_ids'), list):
            continue
        expected = []
        for cue in segment['srt_cue_ids']:
            if type(cue) is not int or cue not in known_ids:
                continue
            if len(owners.get(cue, [])) > 1:
                parts = segment.get('cue_text_parts', [])
                matches = [part for part in parts if isinstance(part, dict) and part.get('cue_id') == cue] if isinstance(parts, list) else []
                if len(matches) != 1 or not nonempty(matches[0].get('text')):
                    continue
                expected.append(matches[0]['text'].strip())
            else:
                expected.append(cue_text[cue])
        if expected and ''.join(str(segment.get('spoken_text', '')).split()) != ''.join(''.join(expected).split()):
            errors.append(f'segment {i+1}: spoken_text drifts from bound SRT text or declared cue_text_parts')
        for guard in segment.get('meaning_guards', []) if isinstance(segment.get('meaning_guards'), list) else []:
            if isinstance(guard, dict) and nonempty(guard.get('content')) and guard['content'].strip() not in ''.join(expected):
                errors.append(f'segment {i+1}: meaning_guards content must belong to this segment, not another partition of a shared cue')
    groups = plan.get('protected_cue_groups')
    if not isinstance(groups, list):
        errors.append('protected_cue_groups: must be a list')
    else:
        for i, group in enumerate(groups):
            label = f'protected_cue_groups {i+1}'
            if not isinstance(group, dict) or not isinstance(group.get('kind'), str) or group['kind'] not in GUARD_KINDS or not nonempty(group.get('reason')):
                errors.append(f'{label}: needs kind and reason')
                continue
            ids = cue_ids(group.get('cue_ids'), label, minimum=2)
            if ids:
                common = set.intersection(*(set(sid for sid, _ in owners.get(cue, [])) for cue in ids))
                if not common and not all(cue in excluded for cue in ids):
                    errors.append(f'{label}: protected meaning is split across segments or exclusions')
    for i, segment in enumerate(segments):
        if not isinstance(segment, dict):
            continue
        label = f'segment {i+1}'
        callbacks = segment.get('callback_refs')
        if not isinstance(callbacks, list):
            errors.append(f'{label}: callback_refs must be a list')
            continue
        for j, callback in enumerate(callbacks):
            prefix = f'{label} callback_refs {j+1}'
            if not isinstance(callback, dict) or not nonempty(callback.get('relation')):
                errors.append(f'{prefix}: needs relation and valid target')
                continue
            target_id = callback.get('target_segment_id')
            target = segment_by_id.get(target_id) if nonempty(target_id) else None
            ids = cue_ids(callback.get('cue_ids'), prefix)
            target_cues = target[1].get('srt_cue_ids') if target is not None else None
            if target is None or ids is None or target[0] >= i or not isinstance(target_cues, list) or not set(ids).issubset(target_cues):
                errors.append(f'{prefix}: target segment or its referenced cues are invalid')

def validate(plan, project, stage='pre-director'):
    errors=[]; warnings=[]; manual_review=[];root=Path(project)
    if not isinstance(plan,dict):return {'passed':False,'errors':['plan must be an object'],'warnings':[]}
    from project_policy import classify_project, requires_visual_decision
    policy = classify_project(root)
    new_decision = requires_visual_decision(root, plan)
    if policy['minimum_semantic_version'] == 2 and plan.get('semantic_contract_version') != 2:
        errors.append('semantic_contract_version: new or unverified studio work requires v2, including silent planning')
    def required(obj,key,label):
        if not isinstance(obj.get(key),str) or not obj[key].strip(): errors.append(f'{label}: missing {key}')
    def check_source(key,hash_key):
        try:
            path=_local(root,plan.get(key));actual=hashlib.sha256(path.read_bytes()).hexdigest()
            if plan.get(hash_key)!=actual:errors.append(f'{key}: source hash drift or missing hash')
        except (ValueError,OSError) as e:errors.append(f'{key}: {e}')
    check_source('source_script','source_sha256')
    if new_decision:
        kind = plan.get('timebase_kind')
        if kind not in ('real_voice_srt', 'authored_screen_timing'):
            errors.append('timebase_kind: new v2 work needs real_voice_srt or explicit authored_screen_timing')
        elif kind == 'real_voice_srt':
            if plan.get('authored_cues'):
                errors.append('real_voice_srt: authored_cues cannot replace real SRT or original voice')
            check_source('audio_source', 'audio_sha256')
        elif plan.get('audio_source') or plan.get('srt_source'):
            errors.append('authored_screen_timing: do not claim real voice or SRT in a silent study plan')
    required(plan,'style_intent','plan')
    if stage=='storyboard':
        if plan.get('design_source')!='design.md':errors.append('storyboard must bind this project design.md')
        check_source('design_source','design_sha256')
    segments=plan.get('segments')
    if not isinstance(segments,list) or not segments:
        return {'passed':False,'errors':errors+['segments must be a non-empty list'],'warnings':warnings}
    seen=set()
    for i,s in enumerate(segments):
        label=f'segment {i+1}'
        if not isinstance(s,dict):errors.append(f'{label}: must be object');continue
        for field in ('id','spoken_text','audience_takeaway','reason','visual_action','reading_plan','handoff'):
            required(s,field,label)
        sid=s.get('id')
        if isinstance(sid,str):
            if sid in seen:errors.append(f'{label}: duplicate id')
            seen.add(sid)
        route=s.get('visual_route')
        if not isinstance(route,str) or route not in ROUTES:
            errors.append(f'{label}: unknown visual_route');route=None
        candidates=s.get('library_candidates')
        if not isinstance(candidates,list) or any(not isinstance(v,str) or not v.strip() for v in candidates):
            errors.append(f'{label}: library_candidates must be a string list')
        elif route in LIBRARY_ROUTES and not candidates:
            required(s,'library_skip_reason',label)
        if plan.get('semantic_contract_version') == 2 and isinstance(candidates, list):
            from resource_handoff import candidate_identity
            for candidate in candidates:
                if not isinstance(candidate, str) or not candidate.strip():
                    continue
                try:
                    identity = candidate_identity(candidate)
                    if identity['source_state'] == 'drift':
                        errors.append(f'{label}: indexed candidate original SHA-256 drift: {candidate}')
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    errors.append(f'{label}: unknown or unavailable library candidate ID {candidate}: {exc}')
        if new_decision and plan.get('semantic_contract_version') == 2:
            _search_and_selection(s, plan, root, errors, warnings, label)
        if route=='image_to_video': required(s,'generation_action',label)
        if route=='hybrid':
            required(s,'responsibilities',label)
            if not isinstance(s.get('uses_image_to_video'),bool):errors.append(f'{label}: hybrid must declare uses_image_to_video')
            if s.get('uses_image_to_video') is True:required(s,'generation_action',label)
        exact=s.get('requires_exact_information')
        if not isinstance(exact,bool):errors.append(f'{label}: requires_exact_information must be boolean')
        if route=='image_to_video' and exact:errors.append(f'{label}: exact information cannot be generated by image-to-video')
        if new_decision and plan.get('semantic_contract_version') == 2:
            numeric_tokens = list(dict.fromkeys(re.findall(r'\d+(?:\.\d+)?%?',
                ' '.join(str(s.get(key, '')) for key in ('spoken_text', 'original_intent', 'visual_action')))))
            focus_flags = []
            requirements = s.get('expression_requirements')
            if isinstance(requirements, list):
                from expression_contract import cue_window
                for left_index, left in enumerate(requirements):
                    if not isinstance(left, dict):
                        continue
                    for right in requirements[left_index+1:]:
                        if not isinstance(right, dict):
                            continue
                        left_ids, right_ids = left.get('cue_ids'), right.get('cue_ids')
                        if not (isinstance(left_ids, list) and left_ids and isinstance(right_ids, list) and right_ids):
                            continue
                        try:
                            left_window = cue_window(root, plan, left_ids)
                            right_window = cue_window(root, plan, right_ids)
                        except (ValueError, KeyError, OSError, TypeError):
                            continue
                        overlap = min(left_window[1], right_window[1]) - max(left_window[0], right_window[0])
                        if overlap <= 0:
                            continue
                        left_attention = left.get('attention') if isinstance(left.get('attention'), dict) else {}
                        right_attention = right.get('attention') if isinstance(right.get('attention'), dict) else {}
                        left_focus, right_focus = left_attention.get('focus'), right_attention.get('focus')
                        left_group, right_group = left_attention.get('parallel_read_group'), right_attention.get('parallel_read_group')
                        left_dominant, right_dominant = left_attention.get('dominant_focus'), right_attention.get('dominant_focus')
                        shared = (isinstance(left_group, str) and bool(left_group.strip()) and left_group == right_group and
                                  isinstance(left_dominant, str) and bool(left_dominant.strip()) and left_dominant == right_dominant)
                        budget_sum = sum(value for value in (left_attention.get('budget_seconds'), right_attention.get('budget_seconds'))
                                         if type(value) in (int, float) and math.isfinite(value))
                        union_seconds = max(left_window[1], right_window[1]) - min(left_window[0], right_window[0])
                        focus_flags.append({'requirement_ids': [left.get('id'), right.get('id')],
                                            'overlap_seconds': round(overlap, 3),
                                            'focus_relation': 'declared_parallel_same_dominant_focus' if shared else
                                                              'same_focus_needs_schedule_review' if left_focus == right_focus else
                                                              'different_focus_needs_schedule_review',
                                            'parallel_read_group': left_group if shared else None,
                                            'dominant_focus': left_dominant if shared else None,
                                            'declared_budget_sum_seconds': round(budget_sum, 3),
                                            'union_window_seconds': round(union_seconds, 3),
                                            'boundary': 'Overlap is not automatically invalid; inspect actual clear/hold timing and small-screen reading.'})
            manual_review.append({'segment_id': s.get('id'),
                                  'original_intent': 'independent source restatement required before formal approval',
                                  'numeric_tokens_in_plan_text': numeric_tokens,
                                  'requires_exact_information_declared': exact,
                                  'evidence_status': 'not_machine_verified',
                                  'requirement_attention': [
                                      {'id': req.get('id'), 'cue_ids': req.get('cue_ids'),
                                       'relation': req.get('relation'), 'must_be_seen': req.get('must_be_seen'),
                                       'focus': req.get('attention', {}).get('focus'),
                                       'camera_or_view': req.get('attention', {}).get('camera_or_view'),
                                       'clear_before': req.get('attention', {}).get('clear_before'),
                                       'budget_seconds': req.get('attention', {}).get('budget_seconds'),
                                       'min_read_seconds': req.get('attention', {}).get('min_read_seconds')}
                                      for req in requirements if isinstance(req, dict) and
                                      isinstance(req.get('attention'), dict)
                                  ] if isinstance(requirements, list) else [],
                                  'focus_window_flags': focus_flags})
            if numeric_tokens and exact is False:
                warnings.append(f'{label}: numeric text exists while requires_exact_information=false; human must confirm whether these are exact claims')
        evidence=s.get('evidence')
        if not isinstance(evidence,list):errors.append(f'{label}: evidence must be a list');continue
        malformed=any(not isinstance(e,dict) or not isinstance(e.get('ref'),str) or not e['ref'].strip() or not isinstance(e.get('verified'),bool) for e in evidence)
        if malformed:errors.append(f'{label}: malformed evidence entry')
        needs_evidence=exact or route in ('official_evidence','sourced_chart')
        if needs_evidence and (not evidence or malformed or any(e.get('verified') is not True for e in evidence if isinstance(e,dict))):
            msg=f'{label}: exact evidence still requires verification'
            (errors if stage=='storyboard' else warnings).append(msg)
    if 'semantic_contract_version' in plan:
        version=plan['semantic_contract_version']
        if type(version) is not int or version not in (1, 2):
            errors.append('semantic_contract_version: unsupported version')
        else:
            _semantic_audit(plan,root,segments,errors,stage)
    if 'preview_contract_version' in plan:
        if plan['preview_contract_version'] != 1 or type(plan['preview_contract_version']) is not int:
            errors.append('preview_contract_version: unsupported version')
        else:
            from resource_handoff import verify_preview
            for segment in segments:
                if isinstance(segment, dict) and isinstance(segment.get('id'), str):
                    result = verify_preview(root, plan, segment['id'])
                    errors.extend(f"segment {segment['id']} preview: {item}" for item in result['errors'])
    return {'passed':not errors,'stage':stage,'segments':len(segments),'errors':errors,'warnings':warnings,
            'manual_review_required': manual_review,
            'boundary':'audit only; no semantic approval, generation, or old-project migration'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['validate']);p.add_argument('--project',required=True,type=Path);p.add_argument('--plan',required=True,type=Path);p.add_argument('--stage',choices=['pre-director','storyboard'],default='pre-director');a=p.parse_args()
    try:result=validate(json.loads(a.plan.read_text(encoding='utf-8')),a.project,a.stage)
    except (OSError,UnicodeDecodeError,json.JSONDecodeError) as e:result={'passed':False,'errors':[str(e)]}
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
