import asyncio
import os
from inspect import isawaitable
from pathlib import Path
from typing import Any, Dict

from astrbot.api import logger
from astrbot.api.all import Star
from astrbot.api.star import StarTools

from ..core.constant import (
    BANNER_PATH,
    CARD_TEMPLATES,
    DEFAULT_TEMPLATE,
    LOGO_PATH,
    MAX_ATTEMPTS,
    RETRY_DELAY,
    get_template_path,
)
from ..core.models import RenderPayload
from ..core.utils import create_qrcode, image_to_base64, parse_rich_text


def load_template(style: str) -> str:
    """加载指定样式的模板内容"""
    path = get_template_path(style)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class Renderer:
    """
    负责将动态数据渲染成图片。
    """

    def __init__(
        self,
        star_instance: Star,
        rai: bool,
        style: str = DEFAULT_TEMPLATE,
        config: Any | None = None,
    ):
        """
        初始化渲染器。
        """
        self.star = star_instance
        self.rai = rai
        self.style = style
        self.config = config or {}
        self.plugin_data_dir = Path(
            StarTools.get_data_dir(plugin_name="astrbot_plugin_bilibili")
        ).resolve()
        self._atri_banner_cache: Dict[str, str] = {}
        self._bot_avatar_fallback = image_to_base64(LOGO_PATH)
        self._bot_avatar_cache: Dict[str, str] = {}
        # 预加载所有模板
        self._templates: Dict[str, str] = {}
        self._load_all_templates()

    def _get_atri_banner(self) -> str:
        """读取配置中第一张安全、有效的 ATRI 顶部图片。"""
        raw_paths = self.config.get("atri_banner_image", [])
        if isinstance(raw_paths, str):
            raw_paths = [raw_paths]
        if not isinstance(raw_paths, list):
            return ""

        mime_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }
        for raw_path in raw_paths:
            if not isinstance(raw_path, str) or not raw_path.strip():
                continue
            try:
                path = Path(raw_path.strip())
                if not path.is_absolute():
                    path = self.plugin_data_dir / path
                path = path.resolve()
                if not path.is_relative_to(self.plugin_data_dir):
                    logger.warning(f"忽略插件数据目录外的 ATRI 顶部图片: {path}")
                    continue
                mime_type = mime_types.get(path.suffix.lower())
                if not mime_type or not path.is_file():
                    continue
                if path.stat().st_size > 10 * 1024 * 1024:
                    logger.warning(f"ATRI 顶部图片超过 10 MB，已忽略: {path}")
                    continue
                cache_key = f"{path}:{path.stat().st_mtime_ns}"
                if cache_key not in self._atri_banner_cache:
                    self._atri_banner_cache = {
                        cache_key: image_to_base64(str(path), mime_type)
                    }
                return self._atri_banner_cache[cache_key]
            except (OSError, ValueError) as exc:
                logger.warning(f"读取 ATRI 顶部图片失败 ({raw_path}): {exc}")
        return ""

    async def _get_bot_qq_avatar(self, platform_id: str = "") -> str:
        """获取指定 OneBot 平台的 Bot QQ 头像，失败时使用本地图标。"""
        if platform_id and platform_id in self._bot_avatar_cache:
            return self._bot_avatar_cache[platform_id]

        context = getattr(self.star, "context", None)
        platform = None
        if context is not None and platform_id:
            get_platform_inst = getattr(context, "get_platform_inst", None)
            if callable(get_platform_inst):
                platform = get_platform_inst(platform_id)

        if platform is None and context is not None and not platform_id:
            platform_manager = getattr(context, "platform_manager", None)
            for candidate in getattr(platform_manager, "platform_insts", ()):
                meta = candidate.meta()
                if getattr(meta, "name", "") == "aiocqhttp":
                    platform = candidate
                    platform_id = str(getattr(meta, "id", "") or "aiocqhttp")
                    break

        if platform is None or getattr(platform.meta(), "name", "") != "aiocqhttp":
            return self._bot_avatar_fallback

        call_action = getattr(getattr(platform, "bot", None), "call_action", None)
        if not callable(call_action):
            return self._bot_avatar_fallback

        try:
            login_info = call_action(action="get_login_info")
            if isawaitable(login_info):
                login_info = await login_info
            qq_number = (
                login_info.get("user_id", "")
                if isinstance(login_info, dict)
                else getattr(login_info, "user_id", "")
            )
            qq_number = str(qq_number or "").strip()
            if qq_number.isdecimal():
                avatar_url = f"https://q1.qlogo.cn/g?b=qq&nk={qq_number}&s=640"
                self._bot_avatar_cache[platform_id] = avatar_url
                return avatar_url
        except Exception as exc:
            logger.warning(f"获取 Bot QQ 头像失败: {exc}")
        return self._bot_avatar_fallback

    def _load_all_templates(self):
        """预加载所有注册的模板"""
        for template_id in CARD_TEMPLATES:
            try:
                self._templates[template_id] = load_template(template_id)
            except Exception as e:
                logger.warning(f"加载模板 {template_id} 失败: {e}")

    def reload_templates(self):
        """重新加载所有模板（用于热更新）"""
        self._templates.clear()
        self._load_all_templates()

    def get_template(self, style: str | None = None) -> str:
        """获取指定样式的模板内容"""
        target_style = style or self.style
        if target_style not in self._templates:
            target_style = DEFAULT_TEMPLATE
        return self._templates.get(target_style, "")

    async def render_dynamic(
        self,
        payload: RenderPayload,
        style: str | None = None,
        platform_id: str = "",
    ):
        """
        将渲染数据字典渲染成最终图片。
        这是该类的主要入口方法。
        """
        # options = {"full_page": True, "type": "png", "quality": None, "scale": "device"}
        options = {
            "full_page": True,
            "type": "jpeg",
            "quality": 95,
            "scale": "device",
            "device_scale_factor_level": "ultra",
        }

        target_style = style or self.style
        tmpl = self.get_template(target_style)
        context = payload.to_template_context()
        if target_style == "atri":
            context["bot_avatar"] = await self._get_bot_qq_avatar(platform_id)
            context["atri_banner"] = self._get_atri_banner()

        for attempt in range(1, MAX_ATTEMPTS + 1):
            render_output = None
            try:
                render_output = await self.star.html_render(
                    tmpl=tmpl,
                    data=context,
                    return_url=False,
                    options=options,
                )
                if (
                    render_output
                    and os.path.exists(render_output)
                    and os.path.getsize(render_output) > 4096
                    and self._validate_image(render_output)
                ):
                    return render_output
            except Exception as e:
                logger.error(f"渲染图片失败 (尝试次数: {attempt}): {e}")

            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(RETRY_DELAY)

        return None  # 所有尝试都失败

    @staticmethod
    def _validate_image(img_path: str) -> bool:
        """验证图片文件是否有效可读"""
        try:
            from PIL import Image

            with Image.open(img_path) as img:
                img.verify()
            return True
        except Exception as e:
            logger.warning(f"图片验证失败 {img_path}: {e}")
            return False

    @staticmethod
    def _build_base_payload(item: Dict[str, Any]) -> RenderPayload:
        author_module = item.get("modules", {}).get("module_author") or {}
        return RenderPayload(
            banner=image_to_base64(BANNER_PATH),
            name=str(author_module.get("name") or ""),
            avatar=str(author_module.get("face") or ""),
            pendant=str((author_module.get("pendant") or {}).get("image") or ""),
            type=str(item.get("type") or ""),
        )

    def _fill_video_payload(
        self, payload: RenderPayload, item: Dict[str, Any], is_forward: bool
    ) -> RenderPayload:
        archive = item["modules"]["module_dynamic"]["major"]["archive"]
        title = str(archive["title"])
        bv = str(archive["bvid"])
        cover_url = str(archive["cover"])
        desc = item.get("modules", {}).get("module_dynamic", {}).get("desc")
        topic = item.get("modules", {}).get("module_dynamic", {}).get("topic")
        content_text = (desc or {}).get("text")

        payload.title = title
        payload.image_urls = [cover_url]
        payload.text = (
            f"投稿了新视频<br>{parse_rich_text(desc, topic)}"
            if content_text
            else "投稿了新视频<br>"
        )
        if not is_forward:
            payload.url = f"https://www.bilibili.com/video/{bv}"
            payload.qrcode = create_qrcode(payload.url)
        return payload

    def _fill_opus_payload(
        self, payload: RenderPayload, item: Dict[str, Any], is_forward: bool
    ) -> RenderPayload:
        opus = item["modules"]["module_dynamic"]["major"]["opus"]
        summary = opus["summary"]
        jump_url = str(opus["jump_url"])
        topic = item["modules"]["module_dynamic"]["topic"]

        payload.summary = str(summary.get("text") or "")
        payload.text = parse_rich_text(summary, topic)
        payload.title = str(opus.get("title") or "")
        payload.image_urls = [str(pic["url"]) for pic in opus.get("pics", [])[:9]]
        if not payload.image_urls and self.rai:
            payload.image_urls = [image_to_base64(LOGO_PATH)]
        if not is_forward:
            payload.url = f"https:{jump_url}"
            payload.qrcode = create_qrcode(payload.url)
        return payload

    @staticmethod
    def _fill_forward_payload(
        payload: RenderPayload, item: Dict[str, Any]
    ) -> RenderPayload:
        desc = item.get("modules", {}).get("module_dynamic", {}).get("desc")
        topic = item.get("modules", {}).get("module_dynamic", {}).get("topic")
        content_text = (desc or {}).get("text")
        if content_text:
            payload.text = parse_rich_text(desc, topic)
        return payload

    def build_render_data(
        self, item: Dict[str, Any], is_forward: bool = False
    ) -> RenderPayload:
        """
        根据从B站API获取的单个动态项目，构建用于渲染的对象。
        is_forward: 标记是否正在处理转发动态
        """
        payload = self._build_base_payload(item)
        item_type = item.get("type")
        if item_type == "DYNAMIC_TYPE_AV":
            return self._fill_video_payload(payload, item, is_forward)
        if item_type in (
            "DYNAMIC_TYPE_DRAW",
            "DYNAMIC_TYPE_WORD",
            "DYNAMIC_TYPE_ARTICLE",
        ):
            return self._fill_opus_payload(payload, item, is_forward)
        if item_type == "DYNAMIC_TYPE_FORWARD":
            return self._fill_forward_payload(payload, item)
        return payload
