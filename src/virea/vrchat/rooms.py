"""Command-based invite/accept/join for the two locally bound accounts only."""

import asyncio
import contextlib
import json
import os
import time
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from .client_ipc import launch_url, select_launch_client, send_to_client
from .client_status import _client_log_text, authentication_status, room_evidence
from .room_feedback import RoomAccessDenied
from .room_invites import received_invitation
from .views import ViewUnavailable, select_target, vrchat_windows


@dataclass(frozen=True)
class RoomClient:
    pid: int
    started: float
    account: str
    room: str


class RoomAuthenticationError(ValueError):
    def __init__(self, roles):
        self.roles = list(roles)
        names = "、".join("AI" if role == "ai" else "观察者" for role in roles)
        super().__init__(
            f"{names} 的游戏 API 已返回 401 Missing Credentials，场景在线但好友和入房认证已失效。"
            "本次未继续发送入房操作；请在对应窗口恢复登录后再试。"
        )


class RoomInvitationRequired(ValueError):
    """No authenticated invitation path is configured; a launch code is not a grant."""


def local_pair(ai_port):
    import psutil

    windows = vrchat_windows()
    pair = {}
    invalid = []
    processes = {}
    for role in ("ai", "observer"):
        target = select_target(windows, role, ai_port)
        process = psutil.Process(target.pid)
        if process.create_time() != target.started:
            raise ValueError("VRChat client changed during room lookup")
        processes[role] = (target, process)
        # Read both clients before judging either sender's API state. On a
        # cold backend, the peer's newer invitation receipt may be unread.
        _client_log_text(process)
    for role, (target, process) in processes.items():
        if process.create_time() != target.started:
            raise ValueError("VRChat client changed during room lookup")
        text = _client_log_text(process)
        if authentication_status(text) == "api_auth_error_in_log":
            invalid.append(role)
            continue
        evidence = room_evidence(text)
        if not evidence:
            label = "AI" if role == "ai" else "观察者"
            raise ValueError(f"{label} 尚无登录并到达房间的记录，请等待游戏加载完成")
        pair[role] = RoomClient(target.pid, target.started, *evidence)
    if invalid:
        raise RoomAuthenticationError(invalid)
    if (
        pair["ai"].pid == pair["observer"].pid
        or pair["ai"].account == pair["observer"].account
    ):
        raise ValueError("两个客户端必须属于不同账号")
    return pair


class RoomAPI:
    """Explicit API session, separate from game authentication.

    Session cookies are supplied by the operator's environment, never scraped
    from a game/browser, placed in URLs, returned to the UI or persisted here.
    The community API can change; a failure is surfaced, never retried as UI.
    """

    def __init__(self, role, *, client=None):
        self.role = role
        self.client = client

    async def request(self, method, path, **kwargs):
        token = os.environ.get(f"VIREA_VRCHAT_{self.role.upper()}_AUTH", "")
        if not token:
            label = "AI" if self.role == "ai" else "观察者"
            raise RoomInvitationRequired(
                f"{label} 的邀请 API 会话未配置，无法自动邀请进入私人房间。"
                "请在房主游戏窗口向另一个账号发送当前房间的邀请并接受，"
                "或配置房主的邀请 API 会话后再点同房间。启动短码不能代替有效邀请。"
            )
        cookies = {"auth": token}
        second = os.environ.get(f"VIREA_VRCHAT_{self.role.upper()}_TWO_FACTOR_AUTH")
        if second:
            cookies["twoFactorAuth"] = second
        async with httpx.AsyncClient(
            base_url="https://api.vrchat.cloud/api/1/",
            cookies=cookies,
            headers={"User-Agent": "VIREA/0.1 (https://github.com/Moonweave-AI/virea)"},
            timeout=10,
            follow_redirects=False,
            trust_env=False,
            transport=self.client,
        ) as client:
            response = await client.request(method, path, **kwargs)
        if response.status_code == 401:
            raise ValueError(
                f"{self.role} 的邀请 API 会话无效（401）；这是独立的工具会话，不代表需要退出游戏"
            )
        if response.status_code == 403:
            raise RoomInvitationRequired(
                "邀请被 VRChat 拒绝（403）；请确认两个账号互为好友且房主有邀请权限。未发送入房命令。"
            )
        if response.status_code == 429:
            raise ValueError("VRChat API 请求受限；本次操作停止，未重复发送")
        if not response.is_success:
            raise ValueError(f"VRChat API returned HTTP {response.status_code}")
        return response.json()

    async def verify(self, expected_account):
        current = await self.request("GET", "auth/user")
        if current.get("id") != expected_account:
            raise ValueError("API 会话与所选游戏账号不一致；操作已停止")


async def instance_short_name(location, *, client=None):
    """Resolve a known instance's launch code, without taking game credentials.

    The community API specification permits this endpoint without an auth
    cookie. It may still deny access; never turn a denial into a UI bypass.
    """
    launch_url(location)
    async with httpx.AsyncClient(
        base_url="https://api.vrchat.cloud/api/1/",
        trust_env=False,
        headers={"User-Agent": "VIREA/0.1 (https://github.com/Moonweave-AI/virea)"},
        timeout=10,
        follow_redirects=False,
        transport=client,
    ) as api:
        response = await api.get(
            "instances/" + quote(location, safe=":~()") + "/shortName"
        )
    if not response.is_success:
        raise ValueError(
            f"无法取得该实例的入房短码（HTTP {response.status_code}）；未发送入房命令"
        )
    value = response.json()
    name = (
        (value.get("shortName") or value.get("secureName"))
        if isinstance(value, dict)
        else None
    )
    if not isinstance(name, str) or not name:
        raise ValueError("实例没有可用的入房短码；需要有效邀请")
    launch_url(location, name)
    return name


class RoomCommands:
    def __init__(
        self,
        *,
        pair=local_pair,
        send=send_to_client,
        api=RoomAPI,
        resolve=instance_short_name,
        select=select_launch_client,
        received=received_invitation,
    ):
        self.pair = pair
        self.send = send
        self.api = api
        self.resolve = resolve
        self.select = select
        self.received = received
        self.lock = asyncio.Lock()
        self.state = {"stage": "idle", "same_instance": False, "error": None}
        self.last_invite = None
        self.invitation = None
        self.task = None

    @property
    def active(self):
        return self.lock.locked()

    async def stop(self):
        if (
            self.task
            and self.task is not asyncio.current_task()
            and not self.task.done()
        ):
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task

    def snapshot(self, *, live_same_instance=None):
        state = self.state.copy()
        # An action result is historical. The service supplies fresh session
        # evidence so a later leave/reconnect cannot preserve an old success,
        # and a successful in-game invitation can clear an earlier rejection.
        # Never replace progress while a command still owns the operation.
        if live_same_instance is not None and not self.active:
            state["same_instance"] = live_same_instance
            if live_same_instance:
                state.update(stage="arrived", error=None)
                state.pop("recovery", None)
                state.pop("affected_roles", None)
            elif state["stage"] == "arrived":
                state.update(
                    stage="unverified",
                    error="暂未确认两个账号仍在同一房间，正在等待最新连接记录。",
                )
        return {
            **state,
            "api_sessions_configured": {
                role: bool(os.environ.get(f"VIREA_VRCHAT_{role.upper()}_AUTH"))
                for role in ("ai", "observer")
            },
        }

    async def run(
        self, action, target, ai_port, *, confirm=None, prepare=None, feedback=None
    ):
        if self.lock.locked():
            raise ValueError("已有房间操作正在执行")
        async with self.lock:
            self.task = asyncio.current_task()
            self.state = {
                "stage": "checking",
                "same_instance": False,
                "error": None,
                "action": action,
                "target": target,
                "requested_target": target,
            }
            try:
                return await self._run(
                    action,
                    target,
                    ai_port,
                    confirm=confirm,
                    prepare=prepare,
                    feedback=feedback,
                )
            except asyncio.CancelledError:
                self.state.update(
                    stage="cancelled", error="房间操作已取消；到达状态尚未确认"
                )
                raise
            except RoomAuthenticationError as exc:
                self.state.update(
                    stage="authentication_required",
                    error=str(exc),
                    recovery="restore_game_session",
                    affected_roles=exc.roles,
                )
                raise
            except RoomInvitationRequired as exc:
                self.state.update(
                    stage="invitation_required",
                    error=str(exc),
                    recovery="send_invitation",
                )
                raise
            except RoomAccessDenied as exc:
                self.state.update(
                    stage="access_denied",
                    error=str(exc),
                    recovery="new_invitation_required",
                )
                raise
            except ViewUnavailable as exc:
                self.state.update(
                    stage="failed", error="两个 VRChat 窗口尚未就绪，房间操作已停止"
                )
                raise ValueError(self.state["error"]) from exc
            except Exception as exc:
                self.state.update(stage="failed", error=str(exc))
                raise
            finally:
                self.task = None

    async def _invite(self, pair, target, ai_port, *, reuse=False):
        other = "observer" if target == "ai" else "ai"
        guest, host = pair[target], pair[other]
        key = (host, guest.pid, guest.started, guest.account)
        if (
            self.last_invite
            and self.last_invite[0] == key
            and time.monotonic() - self.last_invite[1] < 60
        ):
            if reuse and self.invitation and self.invitation[0] == key:
                return self.invitation[1]
            raise ValueError(
                "同一邀请已在一分钟内尝试发送，未重复发送；请等待或查看游戏收到的邀请"
            )
        self.state.update(stage="inviting")
        api = self.api(other)
        await api.verify(host.account)
        if await asyncio.to_thread(self.pair, ai_port) != pair:
            raise ValueError("账号或房间已变化，邀请操作停止")
        # Reserve before POST. Timeout/cancellation is an uncertain outcome,
        # never permission to retry a write or reuse an unconfirmed grant.
        self.last_invite = key, time.monotonic()
        self.invitation = None
        result = await api.request(
            "POST",
            "invite/" + quote(guest.account, safe=""),
            json={"instanceId": host.room},
        )
        details = invitation_details(result, host.account, guest.account, host.room)
        if details is None:
            raise ValueError(
                "邀请接口未确认目标账号和当前房间的有效邀请；未发送入房命令"
            )
        self.invitation = key, details
        return details

    async def _run(
        self, action, target, ai_port, *, confirm=None, prepare=None, feedback=None
    ):
        if (
            target not in {"ai", "observer", "auto"}
            or action not in {"join", "invite", "accept"}
            or (target == "auto" and action != "join")
        ):
            raise ValueError("invalid room command")
        pair = await asyncio.to_thread(self.pair, ai_port)
        if pair["ai"].room == pair["observer"].room:
            self.state.update(stage="arrived", same_instance=True)
            return self.snapshot()
        if target == "auto":
            target = await asyncio.to_thread(
                self.select,
                {role: (client.pid, client.started) for role, client in pair.items()},
            )
            if target not in pair:
                raise ValueError("入房管道不属于已绑定的两个账号")
        other = "observer" if target == "ai" else "ai"
        guest, host = pair[target], pair[other]
        self.state.update(
            target=target,
            host=other,
            direction="观察者加入 AI，保留 AI 当前站位"
            if target == "observer"
            else "AI 加入观察者",
        )
        location, short_name = host.room, None
        private = "~private(" in location
        received = None
        if action == "accept" or (action == "join" and private):
            received = await asyncio.to_thread(self.received, guest, host)
            if received is not None:
                short_name = received.get("shortName")
                self.state.update(
                    stage="invitation_verified", invitation_source="game_notification"
                )
        if action == "invite" or (action == "join" and private and received is None):
            details = await self._invite(pair, target, ai_port, reuse=action == "join")
            short_name = details.get("shortName")
            if action == "invite":
                self.state.update(stage="invitation_sent")
                return self.snapshot()
            self.state.update(stage="invitation_verified", invitation_source="api")
        if action == "accept" and received is None:
            api = self.api(target)
            await api.verify(guest.account)
            notifications = await api.request(
                "GET", "auth/user/notifications", params={"type": "invite", "n": 100}
            )
            invitations = []
            if not isinstance(notifications, list):
                raise ValueError("邀请接口返回格式异常，未发送入房命令")
            for item in notifications:
                details = invitation_details(
                    item, host.account, guest.account, host.room
                )
                if details is not None:
                    invitations.append(details)
            if not invitations:
                raise ValueError("未找到来自另一个已绑定账号、且匹配当前房间的邀请")
            short_name = invitations[0].get("shortName")
        launch_url(location, short_name)  # validate before any IPC mutation
        if private and not short_name:
            short_name = await self.resolve(location)
        current = await asyncio.to_thread(self.pair, ai_port)
        if current != pair:
            raise ValueError("账号或房间已变化，入房操作停止")
        if prepare is not None:
            await prepare(target)
            if await asyncio.to_thread(self.pair, ai_port) != pair:
                raise ValueError("账号或房间已变化，入房操作停止")
        self.state.update(stage="sending")
        await asyncio.to_thread(
            self.send, guest.pid, guest.started, location, short_name
        )
        self.state.update(stage="waiting_for_arrival")
        deadline = time.monotonic() + 45
        confirmation_sent = False
        next_feedback = 0
        while time.monotonic() < deadline:
            await asyncio.sleep(0.5)
            try:
                current = await asyncio.to_thread(self.pair, ai_port)
            except RoomAuthenticationError:
                raise  # Authentication loss is not a normal scene-loading interval.
            except ValueError:
                continue  # no arrival event yet while travelling
            if any(
                (current[r].pid, current[r].started, current[r].account)
                != (pair[r].pid, pair[r].started, pair[r].account)
                for r in pair
            ):
                raise ValueError("客户端身份已变化，未确认入房")
            if current[other].room != location:
                raise ValueError("被加入的账号已离开原房间，未确认同房间")
            if current[target].room == location:
                self.state.update(stage="arrived", same_instance=True)
                return self.snapshot()
            if confirm is not None and not confirmation_sent:
                self.state.update(stage="confirming_join")
                await confirm(guest, host)
                confirmation_sent = True
                self.state.update(stage="waiting_for_arrival")
                deadline = time.monotonic() + 45
            if feedback is not None and time.monotonic() >= next_feedback:
                error = await feedback(target, guest)
                next_feedback = time.monotonic() + 2
                if error:
                    raise RoomAccessDenied(error)
        raise ValueError(
            "入房命令已交给游戏，但两端未确认同房间；检查实例权限或游戏提示"
        )


def invitation_details(item, host, guest, location):
    """Validate the server-issued invitation, never infer access from a short code."""
    if (
        not isinstance(item, dict)
        or item.get("type") != "invite"
        or item.get("senderUserId") != host
    ):
        return None
    if item.get("receiverUserId", guest) != guest:
        return None
    details = item.get("details", {})
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except ValueError:
            return None
    if not isinstance(details, dict) or details.get("worldId") != location:
        return None
    launch_url(location, details.get("shortName"))
    return details
