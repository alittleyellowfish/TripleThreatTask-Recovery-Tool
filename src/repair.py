"""Restore the Mirrorwood Yucong encounter in a single PBZS gameplay slot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from hashlib import sha256
from pathlib import Path
import re
import sys
from tempfile import mkdtemp
from typing import Callable

from game_location import is_game_exe
from pbz_support.compatibility import resolve_key
from pbz_support.compression import OpenOodleCodec
from pbz_support.core import EditorError, LosslessJSON, MAX_FILE_BYTES, PBZSContainer


QUEST = '/Game/PBZstory/PBZQuest/Branch/SanMianHunDun.SanMianHunDun_C'
WEAPON = 'CiGuHunDun'
VESSEL = 'TU_18001'
EMPTY = 'None'
STARTED = 'EQuestCompletion::QC_Started'
FAILED = 'EQuestCompletion::QC_Failed'
BRANCH_COMPLETED = 'EBranchType::BranchCompleted'
BRANCH_ACTIVE = 'EBranchType::BranchActivating'
BRANCH_UNSTARTED = 'EBranchType::None'
UNSET_DATE = '0001.01.01-00.00.00'
SAVE_DATE = '%Y.%m.%d-%H.%M.%S'
GAMEPLAY_SLOT = re.compile(r'(?:AutoSave|ManualSave|NightmareRun)\d+\Z')

TAG_PREFIX = 'fjzl.三头魔偶.'
REQUIRED_TAGS = (
    'xg.三头娃娃.挑战成功',
    'fjzl.风雪数据层.激活',
    *(TAG_PREFIX + f'记忆之花{i}' for i in range(1, 4)),
)
REMATCH_TAGS = frozenset(TAG_PREFIX + suffix for suffix in (
    '激活', '出场', '死亡', 'p2', '击杀成就计数',
))
SPAWNERS = (
    'BP_AISpawner_C_UAID_E89C25A75434CBCC02_1307783693',
    'BP_AISpawner_C_UAID_E89C25A75433A2D602_1084061085',
)
FLOW_ACTORS = (
    'BP_FlowActor_C_UAID_E89C25A75433A3D602_1809970265',
    'BP_FlowActor_C_UAID_E89C25A75433A3D602_1816841266',
)
FOREST = 'PBZ_Fujizhilin_WP'
ARENA_MUSIC = 'PBZMusicVolume_UAID_74563CB5C562129202_1746865239'
REMATCH_BOSSES = ('BP_Monster_YuCong_P1', 'BP_Monster_YuCong')
# IDs matched against the installed map and the ChuChang, S2, RuZhan and Death flows.
REMATCH_NODES = (
    'F6BBF7EC4111EB864AD607AF1825EEE3',
    '9245389346DEB0FC21CE62B413DC423D',
    '60AD442E44FDB0EEACCCB1AE6A77328A',
    '1076758D46FCE9248D9B9A9E9E21766B',
    '1D46270943E7B1894E9DE0B5B086B5EB',
    '7F2970B84E7596BA64DAA8ACC410A834',
    f'{FOREST}{SPAWNERS[0]}_039D715047253F4FB420EC845AEF110F',
    f'{FOREST}-{FLOW_ACTORS[1]}_11987A964FA136E4C30A7CBB45757552',
)


@dataclass(frozen=True)
class RepairResult:
    path: Path
    slot: str
    saved_at: datetime
    refunded: bool
    replacement_weapon: str | None
    continue_slot: str | None
    output_sha256: str


class QuestStatusError(EditorError):
    labels = {
        STARTED: '进行中',
        'EQuestCompletion::QC_Succeded': '已完成',
        'EQuestCompletion::QC_Succeeded': '已完成',
        'EQuestCompletion::QC_NotStarted': '未开始',
    }

    def __init__(self, state):
        self.state_label = self.labels.get(state, '未能识别') if isinstance(state, str) else '未能识别'
        super().__init__(f'最新存档槽的「三面混沌」状态为「{self.state_label}」。')


def require(condition, message):
    if not condition:
        raise EditorError(message)


def latest_slot(entries):
    saved = []
    for entry in entries:
        if not GAMEPLAY_SLOT.fullmatch(entry['name']):
            continue
        system = entry['json'].get('PBZGameSystem')
        require(isinstance(system, dict), f"{entry['name']} 缺少游戏进度信息。")
        date = system.get('DateTimeString')
        try:
            timestamp = datetime.strptime(date, SAVE_DATE)
        except (TypeError, ValueError) as error:
            raise EditorError(f"无法识别 {entry['name']} 的保存时间。") from error
        saved.append((timestamp, entry))

    require(saved, '存档内没有可识别的自动档或手动档。')
    latest_date = max(date for date, _ in saved)
    tied = [entry for date, entry in saved if date == latest_date]
    if len(tied) == 1:
        return latest_date, tied[0]

    advanced = next((e['json'] for e in entries if e['name'] == '__Advanced__'), {})
    selected = next((e for e in tied if e['name'] == advanced.get('LastContinueSlot')), None)
    if selected is not None:
        return latest_date, selected
    require(all(e['raw'] == tied[0]['raw'] for e in tied), '有多个内容不同的最新存档槽，无法自动确定目标。')
    return latest_date, tied[0]


def restore_quest(document: LosslessJSON):
    quests = document.value['Narrative']['NarrativeSavedQuests']
    found = [(i, quest) for i, quest in enumerate(quests) if quest.get('QuestClass') == QUEST]
    require(len(found) == 1, '这个存档槽没有唯一的「三面混沌」任务。')
    index, quest = found[0]
    if quest.get('QuestCompletion') != FAILED:
        raise QuestStatusError(quest.get('QuestCompletion'))
    branches = {branch['BranchID']: branch for branch in quest['QuestBranches']}
    require(len(branches) == len(quest['QuestBranches']), '「三面混沌」包含重复分支。')
    completed = quest['CompletedBranches']
    for name in ('S1', 'S2', 'S3', 'S5', 'S6'):
        require(name in completed and branches.get(name, {}).get('BranchType') == BRANCH_COMPLETED,
                f'「三面混沌」分支 {name} 与已验证的两阶段失败流程不一致。')
    require(branches.get('S7', {}).get('BranchType') == BRANCH_UNSTARTED,
            '「三面混沌」已有第三阶段分支记录。')
    require(branches['S3'].get('TasksProgress') in ([0, 0, 0], [1, 1, 1]), '无法识别三朵记忆之花的记录。')
    quest['QuestCompletion'] = STARTED
    quest['CompletedBranches'] = [name for name in completed if name not in ('S5', 'S6')]
    branches['S3']['TasksProgress'] = [1, 1, 1]
    branches['S5'].update(BranchType=BRANCH_ACTIVE, DirtyTime=branches['S3']['DirtyTime'])
    branches['S6'].update(BranchType=BRANCH_UNSTARTED, DirtyTime=UNSET_DATE)
    document.set_raw(('Narrative', 'NarrativeSavedQuests', index),
                     json.dumps(quest, ensure_ascii=True, allow_nan=False, separators=(',', ':')))


def restore_encounter(document: LosslessJSON):
    pipeline = document.value['EventPipeline']
    tags = pipeline['GlobalTags']
    require(isinstance(tags, list) and set(REQUIRED_TAGS).issubset(tags),
            '缺少首次击杀、雪天镜林或三朵记忆之花的世界记录。')
    require(REMATCH_TAGS.issubset(tags) and TAG_PREFIX + 'p3' not in tags,
            '镜林第二战的世界记录与已验证的两阶段失败流程不一致。')
    saved_spawners = document.value['AISystem']['SpawnerSaveData']
    require(all(FOREST + spawner in saved_spawners for spawner in SPAWNERS)
            and all(node in pipeline['ExecuteNodeGuid'] for node in REMATCH_NODES),
            '镜林的刷怪器或战斗事件与当前工具支持的游戏版本不一致。')
    document.set(('EventPipeline', 'GlobalTags'), [tag for tag in tags if tag not in REMATCH_TAGS])

    for node in REMATCH_NODES:
        document.remove(('EventPipeline', 'ExecuteNodeGuid', node))
    for actor in (*SPAWNERS, *FLOW_ACTORS):
        name = f'{FOREST}-{actor}'
        for section in ('ComponentInfoJson', 'ComponentsOwnerActorInfo'):
            document.remove(('EventPipeline', section, name))
        document.remove(('LevelActorManager', name))
    for spawner in SPAWNERS:
        document.remove(('AISystem', 'SpawnerSaveData', FOREST + spawner))
    if ARENA_MUSIC in document.value['LevelActorManager']:
        document.remove(('LevelActorManager', ARENA_MUSIC, 'ClearEnemy'))


def restore_boss_records(document: LosslessJSON):
    slot = document.value
    cycle = slot['PBZGameSystem']['CycleCount']
    require(type(cycle) is int and cycle >= 0, '无法识别存档的周目。')
    for name in REMATCH_BOSSES:
        records = slot['BossRecord'][name]['Records']
        victories = [(key, value) for key, value in records.items()
                     if key.startswith(f'{cycle}_') and value.get('KillCount', 0) > 0]
        require(len(victories) == 1, '镜林玉琮的两个阶段需要各有一条本周目的击杀记录。')
        key, record = victories[0]
        attempts = record.get('AttemptCount')
        require(record['KillCount'] == 1 and type(attempts) is int and attempts >= 1,
                '无法识别镜林玉琮的战绩结构。')
        if attempts == 1:
            document.remove(('BossRecord', name, 'Records', key))
            if not document.value['BossRecord'][name]['Records']:
                document.remove(('BossRecord', name))
        else:
            at = ('BossRecord', name, 'Records', key)
            document.set(at + ('AttemptCount',), attempts - 1)
            document.remove(at + ('KillCount',))
            document.remove(at + ('BestTimeMs',))


def tempered(record) -> bool:
    value = record.get('AlreadySnapSoul')
    require(type(value) is bool or (type(value) is int and value in (0, 1)),
            '无法确认「刺骨混沌」是否铸魂。')
    return bool(value)


def remove_weapon_references(document: LosslessJSON) -> str | None:
    inventory = document.value['Inventory']
    replacement = None
    for weapons_key, index_key, current_key in (
        ('MainWeapons', 'CurrentWeaponIndex', 'CurrentMainWeaponID'),
        ('ZlgwSavedMainWeapons', 'ZlgwSavedCurrentWeaponIndex', 'ZlgwSavedCurrentMainWeaponID'),
        ('ForcedLoadoutMainWeapons', 'ForcedLoadoutCurrentWeaponIndex', 'ForcedLoadoutCurrentMainWeaponID'),
    ):
        weapons = inventory.get(weapons_key, [])
        equipped = inventory.get(current_key)
        if WEAPON not in weapons and equipped != WEAPON:
            continue
        require(isinstance(weapons, list) and all(isinstance(w, str) for w in weapons)
                and WEAPON in weapons, '无法识别引用「刺骨混沌」的装备配置。')
        require(weapons_key == 'MainWeapons' or not inventory.get('ForcedLoadoutActive', False),
                '当前有剧情强制装备，请换回普通装备后再存档。')
        updated = [EMPTY if weapon == WEAPON else weapon for weapon in weapons]
        owned = inventory['MainWeaponInfos']
        available = [i for i, weapon in enumerate(updated) if weapon in owned and weapon != WEAPON]
        if not available:
            fallback = next((w for w in ('Long', 'Tang', *owned) if w in owned and w != WEAPON), None)
            require(fallback is not None, '找不到可替换已装备「刺骨混沌」的主武器。')
            available = [weapons.index(WEAPON)]
            updated[available[0]] = fallback
        document.set(('Inventory', weapons_key), updated)
        current_index = inventory.get(index_key)
        removed_selected = type(current_index) is int and 0 <= current_index < len(weapons) and weapons[current_index] == WEAPON
        if equipped == WEAPON or removed_selected:
            document.set(('Inventory', index_key), available[0])
            document.set(('Inventory', current_key), updated[available[0]])
            if weapons_key == 'MainWeapons':
                replacement = updated[available[0]]

    require(document.value['Inventory'].get('ForcedLoadoutWeaponID') != WEAPON,
            '当前有剧情指定武器「刺骨混沌」，请退出该剧情装备状态后再存档。')
    return replacement


def restore_rewards(document: LosslessJSON) -> tuple[bool, str | None]:
    slot = document.value
    inventory = slot['Inventory']
    weapon = inventory['MainWeaponInfos'].get(WEAPON)
    require(isinstance(weapon, dict), '最新存档槽没有「刺骨混沌」。')
    require(weapon.get('FirstAcquiredCycle') == slot['PBZGameSystem']['CycleCount'],
            '这把「刺骨混沌」来自其他周目，无法确认属于本次击杀。')
    refund = tempered(weapon)
    if refund:
        vessel = inventory['InventoryInfos'].get(VESSEL)
        require(isinstance(vessel, dict), '已铸魂，但缺少「最初的混沌容器」的消耗记录。')
        current, total = vessel.get('CurrentAmount'), vessel.get('MaxAmount')
        require(type(current) is int and type(total) is int and 0 <= current < total,
                '「最初的混沌容器」的持有量和累计获得量不符合消耗记录。')
        document.set(('Inventory', 'InventoryInfos', VESSEL, 'CurrentAmount'), current + 1)
    replacement = remove_weapon_references(document)
    document.remove(('Inventory', 'MainWeaponInfos', WEAPON))
    require(not _contains_weapon(document.value['Inventory']),
            '背包里有无法识别的「刺骨混沌」引用。')
    return refund, replacement


def _contains_weapon(value) -> bool:
    if isinstance(value, dict):
        return WEAPON in value or any(_contains_weapon(entry) for entry in value.values())
    if isinstance(value, list):
        return any(_contains_weapon(entry) for entry in value)
    return value == WEAPON


def patch_slot(raw: bytes) -> tuple[bytes, bool, str | None]:
    try:
        document = LosslessJSON(raw)
        restore_quest(document)
        restore_encounter(document)
        restore_boss_records(document)
        refunded, replacement = restore_rewards(document)
        return document.bytes(), refunded, replacement
    except (KeyError, TypeError, IndexError, AttributeError, RecursionError) as error:
        raise EditorError('存档的任务、首领或物品结构与已验证的版本不符。') from error


def repair_save(
    source: Path,
    game_exe: Path,
    output_dir: Path,
    *,
    on_progress: Callable[[str, str, datetime], None] | None = None,
) -> RepairResult:
    source = source.resolve(strict=True)
    require(source.is_file() and source.suffix.casefold() == '.sav', '请选择一个 .sav 文件。')
    require(12 <= source.stat().st_size <= MAX_FILE_BYTES, '存档文件大小无效。')
    require(is_game_exe(game_exe), '请选择游戏安装目录下 platform/steam/PBZ.exe。')
    raw = source.read_bytes()
    key, _ = resolve_key(game_exe.resolve().parents[2], raw)
    resources = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    container = PBZSContainer(key, OpenOodleCodec(resources / 'native'))
    entries = container.decode(raw)
    saved_at, target = latest_slot(entries)
    name = target['name']
    if on_progress:
        on_progress('repair', name, saved_at)
    patched, refunded, replacement = patch_slot(target['raw'])
    rebuilt = container.encode(entries, {name: patched})
    if on_progress:
        on_progress('verify', name, saved_at)
    reloaded = container.decode(rebuilt)
    require(len(entries) == len(reloaded), '生成存档的槽数校验失败。')
    for original, result in zip(entries, reloaded):
        require(original['name'] == result['name'], '生成存档的槽顺序校验失败。')
        if original['name'] == name:
            require(result['raw'] == patched and result['json']['Player'] == original['json']['Player'],
                    '生成存档的修复内容或角色数据校验失败。')
        else:
            require(original['block'] == result['block'], f"{original['name']} 发生意外变化。")

    output_dir = output_dir.resolve(strict=True)
    folder = Path(mkdtemp(prefix='PBZ-已修复-', dir=output_dir))
    path = folder / 'PBZSaveGame.sav'
    try:
        with path.open('xb') as stream:
            stream.write(rebuilt)
        require(path.read_bytes() == rebuilt, '输出文件回读校验失败。')
    except BaseException:
        path.unlink(missing_ok=True)
        folder.rmdir()
        raise
    advanced = next((entry['json'] for entry in entries if entry['name'] == '__Advanced__'), {})
    continue_slot = advanced.get('LastContinueSlot')
    return RepairResult(path, name, saved_at, refunded, replacement,
                        continue_slot if isinstance(continue_slot, str) else None,
                        sha256(rebuilt).hexdigest())
