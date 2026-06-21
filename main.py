import json
import time
import asyncio
from pathlib import Path
from typing import Dict, List, Optional

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Plain, At
from astrbot.core.utils.astrbot_path import get_astrbot_data_path


PLUGIN_NAME = "astrbot_plugin_brewery"

# 材料中英文映射
MATERIAL_NAMES = {
    "sorghum": "高粱",
    "rice": "大米",
    "wheat": "小麦",
    "corn": "玉米",
    "grape": "葡萄",
    "barley": "大麦",
    "yeast": "酒曲",
    "water": "泉水"
}
# 反向映射：中文名称→材料ID
MATERIAL_IDS = {v: k for k, v in MATERIAL_NAMES.items()}

# 配方固定ID映射（永久不变，避免配置顺序调整导致历史数据错乱）
RECIPE_ID_MAP = {
    # 国酒系列
    "maotai_flavor": "101",
    "rice_wine": "102",
    "qingxiang_fenjiu": "103",
    "nongxiang_laojiao": "104",
    # 洋酒系列
    "red_wine": "201",
    "whiskey": "202",
    "oak_brandy": "203",
    "grain_vodka": "204",
}


@register(PLUGIN_NAME, "AstrBot Dev", "沉浸式酿酒系统插件", "1.0.0", "")
class BreweryPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.context = context
        
        # 数据目录
        self.data_dir = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 加载配置：优先使用官方注入的配置，兼容旧版本则手动读取
        if config is not None:
            self.config = dict(config)
        else:
            self._load_config()
        
        # 用户数据文件
        self.users_file = self.data_dir / "users.json"
        self._load_users()
        
        # 后台陈酿任务
        self._aging_task = asyncio.create_task(self._aging_worker())
        
        logger.info(f"[酿酒大师] 插件加载完成，共加载 {len(self.users)} 位用户数据")

    def _load_config(self):
        """手动加载配置文件（兼容旧版本 AstrBot）"""
        config_path = Path(get_astrbot_data_path()) / "config" / f"{PLUGIN_NAME}_config.json"
        default_config = self._get_default_config()
        
        if not config_path.exists():
            self.config = default_config
            # 自动写入默认配置文件，方便后台可视化管理
            try:
                config_path.parent.mkdir(parents=True, exist_ok=True)
                temp_path = config_path.with_suffix('.tmp')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(default_config, f, ensure_ascii=False, indent=2)
                temp_path.replace(config_path)
            except Exception as e:
                logger.warning(f"[酿酒大师] 写入默认配置文件失败: {e}")
            return
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
            # 递归合并默认配置，补全缺失键
            merged_config = self._merge_config(default_config, user_config)
            self.config = merged_config
            
            # 如果用户配置缺少字段，自动回写补全
            if merged_config != user_config:
                try:
                    temp_path = config_path.with_suffix('.tmp')
                    with open(temp_path, 'w', encoding='utf-8') as f:
                        json.dump(merged_config, f, ensure_ascii=False, indent=2)
                    temp_path.replace(config_path)
                    logger.info(f"[酿酒大师] 配置文件已自动补全新增字段")
                except Exception as e:
                    logger.warning(f"[酿酒大师] 回写配置文件失败: {e}")
        except Exception as e:
            logger.error(f"[酿酒大师] 读取配置文件失败: {e}，使用默认配置")
            self.config = default_config

    def _get_default_config(self) -> dict:
        """获取默认配置，与 _conf_schema.json 保持完全一致"""
        return {
            "economy": {
                "start_coins": 1000,
                "daily_sign_coins": 50
            },
            "materials": {
                "sorghum": 10,
                "rice": 8,
                "wheat": 12,
                "corn": 9,
                "grape": 15,
                "barley": 11,
                "yeast": 5,
                "water": 3
            },
            "recipes": {
                "chinese_liquors": {
                    "maotai_flavor": {
                        "name": "酱香陈酿",
                        "materials": {
                            "sorghum": 5, "rice": 0, "wheat": 3, "corn": 0,
                            "grape": 0, "barley": 0, "yeast": 2, "water": 5
                        },
                        "brew_time": 60,
                        "base_price": 200,
                        "base_quality": 1,
                        "aging_bonus": 0.5
                    },
                    "rice_wine": {
                        "name": "绍兴黄酒",
                        "materials": {
                            "sorghum": 0, "rice": 5, "wheat": 0, "corn": 0,
                            "grape": 0, "barley": 0, "yeast": 1, "water": 4
                        },
                        "brew_time": 45,
                        "base_price": 120,
                        "base_quality": 1,
                        "aging_bonus": 0.3
                    },
                    "qingxiang_fenjiu": {
                        "name": "清香汾酒",
                        "materials": {
                            "sorghum": 4, "rice": 0, "wheat": 0, "corn": 0,
                            "grape": 0, "barley": 3, "yeast": 2, "water": 4
                        },
                        "brew_time": 50,
                        "base_price": 160,
                        "base_quality": 1,
                        "aging_bonus": 0.4
                    },
                    "nongxiang_laojiao": {
                        "name": "浓香老窖",
                        "materials": {
                            "sorghum": 3, "rice": 2, "wheat": 2, "corn": 2,
                            "grape": 0, "barley": 0, "yeast": 2, "water": 5
                        },
                        "brew_time": 70,
                        "base_price": 240,
                        "base_quality": 2,
                        "aging_bonus": 0.6
                    }
                },
                "western_liquors": {
                    "red_wine": {
                        "name": "庄园红葡萄酒",
                        "materials": {
                            "sorghum": 0, "rice": 0, "wheat": 0, "corn": 0,
                            "grape": 8, "barley": 0, "yeast": 1, "water": 2
                        },
                        "brew_time": 90,
                        "base_price": 300,
                        "base_quality": 2,
                        "aging_bonus": 0.8
                    },
                    "whiskey": {
                        "name": "麦芽威士忌",
                        "materials": {
                            "sorghum": 0, "rice": 0, "wheat": 0, "corn": 2,
                            "grape": 0, "barley": 6, "yeast": 2, "water": 4
                        },
                        "brew_time": 120,
                        "base_price": 450,
                        "base_quality": 2,
                        "aging_bonus": 1.0
                    },
                    "oak_brandy": {
                        "name": "橡木白兰地",
                        "materials": {
                            "sorghum": 0, "rice": 0, "wheat": 0, "corn": 0,
                            "grape": 10, "barley": 0, "yeast": 2, "water": 3
                        },
                        "brew_time": 150,
                        "base_price": 520,
                        "base_quality": 3,
                        "aging_bonus": 1.2
                    },
                    "grain_vodka": {
                        "name": "谷物伏特加",
                        "materials": {
                            "sorghum": 0, "rice": 0, "wheat": 4, "corn": 4,
                            "grape": 0, "barley": 0, "yeast": 2, "water": 5
                        },
                        "brew_time": 100,
                        "base_price": 380,
                        "base_quality": 2,
                        "aging_bonus": 0.7
                    }
                }
            },
            "aging": {
                "aging_cycle": 300,
                "max_quality": 5,
                "cellar_slots": 3
            }
        }

    def _merge_config(self, default: dict, user: dict) -> dict:
        """递归合并用户配置到默认配置，补全缺失的键"""
        result = default.copy()
        for key, value in user.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_config(result[key], value)
            else:
                result[key] = value
        return result

    def _load_users(self):
        """加载用户数据"""
        if self.users_file.exists():
            try:
                with open(self.users_file, 'r', encoding='utf-8') as f:
                    self.users = json.load(f)
            except Exception as e:
                logger.error(f"[酿酒大师] 读取用户数据失败: {e}")
                self.users = {}
        else:
            self.users = {}
            self._save_users()

    def _save_users(self):
        """保存用户数据（原子写入，防止文件损坏）"""
        try:
            temp_file = self.users_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.users, f, ensure_ascii=False, indent=2)
            # 原子替换原文件，杜绝写入崩溃导致数据损坏
            temp_file.replace(self.users_file)
        except Exception as e:
            logger.error(f"[酿酒大师] 保存用户数据失败: {e}")

    def _check_brew_finish(self, user_data: dict):
        """检查用户酿造是否完成，自动收获到背包"""
        brewing = user_data.get('brewing')
        if not brewing:
            return
        
        now = time.time()
        if now >= brewing['end_time']:
            recipes = self._get_all_recipes()
            recipe = recipes.get(brewing['recipe_id'], {})
            
            wine = {
                'id': f"wine_{int(now)}",
                'recipe_id': brewing['recipe_id'],
                'name': brewing['name'],
                'quality': recipe.get('base_quality', 1),
                'brew_time': now,
                'aging_time': 0,
            }
            
            user_data['inventory'].append(wine)
            user_data['brewing'] = None
            user_data['total_brewed'] = user_data.get('total_brewed', 0) + 1
            self._save_users()

    def _get_user(self, user_id: str, user_name: str = "") -> dict:
        """获取或创建用户数据，自动同步昵称、检查酿造完成"""
        if user_id not in self.users:
            start_coins = self.config.get('economy', {}).get('start_coins', 1000)
            self.users[user_id] = {
                'name': user_name,
                'coins': start_coins,
                'materials': {},
                'inventory': [],
                'cellar': [],
                'brewing': None,
                'total_earned': 0,
                'total_brewed': 0,
                'last_sign': 0,
            }
            self._save_users()
        else:
            # 同步更新用户昵称
            if user_name and self.users[user_id].get('name') != user_name:
                self.users[user_id]['name'] = user_name
                self._save_users()
        
        # 自动检查酿造是否完成
        self._check_brew_finish(self.users[user_id])
        return self.users[user_id]

    def _get_all_recipes(self) -> Dict[str, dict]:
        """获取所有配方（固定数字ID，避免配置顺序变化导致历史数据错乱）"""
        recipes = {}
        recipes_config = self.config.get('recipes', {})
        
        chinese = recipes_config.get('chinese_liquors', {})
        for rid_key, rdata in chinese.items():
            if rid_key in RECIPE_ID_MAP:
                recipe_id = RECIPE_ID_MAP[rid_key]
                recipes[recipe_id] = {**rdata, 'type': '国酒', 'recipe_key': rid_key}
        
        western = recipes_config.get('western_liquors', {})
        for rid_key, rdata in western.items():
            if rid_key in RECIPE_ID_MAP:
                recipe_id = RECIPE_ID_MAP[rid_key]
                recipes[recipe_id] = {**rdata, 'type': '洋酒', 'recipe_key': rid_key}
        
        return recipes

    def _get_materials_price(self) -> Dict[str, int]:
        """获取材料价格表"""
        return self.config.get('materials', {})

    async def _aging_worker(self):
        """后台陈酿处理协程，每分钟检查一次，自动处理酿造完成与品质提升"""
        while True:
            try:
                # 每次循环读取最新配置，保证修改后立即生效
                cycle = self.config.get('aging', {}).get('aging_cycle', 300)
                max_quality = self.config.get('aging', {}).get('max_quality', 5)
                recipes = self._get_all_recipes()
                
                now = time.time()
                updated = False
                
                for user_id, user_data in self.users.items():
                    # 后台自动检查酿造完成
                    brewing = user_data.get('brewing')
                    if brewing and now >= brewing['end_time']:
                        recipe = recipes.get(brewing['recipe_id'], {})
                        wine = {
                            'id': f"wine_{int(now)}",
                            'recipe_id': brewing['recipe_id'],
                            'name': brewing['name'],
                            'quality': recipe.get('base_quality', 1),
                            'brew_time': now,
                            'aging_time': 0,
                        }
                        user_data['inventory'].append(wine)
                        user_data['brewing'] = None
                        user_data['total_brewed'] = user_data.get('total_brewed', 0) + 1
                        updated = True
                    
                    # 处理酒窖陈酿
                    cellar = user_data.get('cellar', [])
                    if not cellar:
                        continue
                    
                    # 倒序遍历，安全删除无效槽位
                    for idx in range(len(cellar)-1, -1, -1):
                        slot = cellar[idx]
                        wine = slot.get('wine')
                        # 清理无效槽位
                        if not wine:
                            cellar.pop(idx)
                            updated = True
                            continue
                        
                        elapsed = now - slot['start_time']
                        cycles_passed = int(elapsed // cycle)
                        
                        if cycles_passed > 0:
                            recipe = recipes.get(wine['recipe_id'], {})
                            bonus = recipe.get('aging_bonus', 0.3) * cycles_passed
                            new_quality = min(wine['quality'] + bonus, max_quality)
                            wine['quality'] = round(new_quality, 1)
                            wine['aging_time'] = wine.get('aging_time', 0) + cycles_passed * cycle
                            # 保留剩余不足一周期的时间，避免重置周期
                            slot['start_time'] = now - (elapsed % cycle)
                            updated = True
                
                if updated:
                    self._save_users()
                    
            except Exception as e:
                logger.error(f"[酿酒大师] 陈酿后台任务出错: {e}")
            
            await asyncio.sleep(60)

    # ========== 指令注册 ==========

    @filter.command("酿酒帮助")
    async def brewery_help(self, event: AstrMessageEvent):
        """酿酒系统主菜单，查看所有可用指令"""
        help_text = """🍶 酿酒大师 - 系统主菜单

📜 基础指令：
/酿酒帮助 - 显示此帮助菜单
/酿酒签到 - 每日领取金币
/酿酒背包 - 查看材料和酒库存
/酒窖 - 查看陈酿中的酒

📚 配方教程：
/配方列表 - 查看所有酿酒配方
/配方 <配方ID> - 查看具体配方详情

🛒 市场交易：
/酿酒市场 - 查看材料价格表
/酿酒购买 <材料名> <数量> - 购买酿酒材料
/出售 <背包序号> - 出售酒获得金币

🍺 酿造系统：
/开始酿造 <配方ID> - 开始酿酒
/酿造状态 - 查看当前酿造进度

🏆 排行榜：
/富豪榜 - 金币排行榜
/酿酒大师榜 - 酿酒数量排行榜

💡 提示：酒放入酒窖陈酿可提升品质星级，售价更高哦！"""
        yield event.plain_result(help_text)

    @filter.command("酿酒签到")
    async def daily_sign(self, event: AstrMessageEvent):
        """每日签到领取金币（北京时间0点刷新）"""
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
        user = self._get_user(user_id, user_name)
        
        now = time.time()
        last_sign = user.get('last_sign', 0)
        
        # 按北京时间（东八区）自然日判断
        today = int((now + 8 * 3600) // 86400)
        last_day = int((last_sign + 8 * 3600) // 86400)
        
        if today == last_day:
            yield event.plain_result("❌ 你今天已经签到过了，明天再来吧~")
            return
        
        sign_coins = self.config.get('economy', {}).get('daily_sign_coins', 50)
        user['coins'] += sign_coins
        user['last_sign'] = now
        self._save_users()
        
        yield event.plain_result(f"✅ 签到成功！获得 {sign_coins} 金币\n当前金币：{user['coins']}")

    @filter.command("酿酒背包")
    async def inventory(self, event: AstrMessageEvent):
        """查看个人背包"""
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
        user = self._get_user(user_id, user_name)
        
        # 材料部分
        materials = user.get('materials', {})
        mat_text = "📦 材料库存：\n"
        has_mat = False
        for mid, count in materials.items():
            if count > 0:
                name = MATERIAL_NAMES.get(mid, mid)
                mat_text += f"  {name}: {count} 份\n"
                has_mat = True
        if not has_mat:
            mat_text += "  暂无材料\n"
        
        # 酒品部分
        wines = user.get('inventory', [])
        wine_text = "\n🍾 酒品库存：\n"
        if wines:
            for idx, wine in enumerate(wines, 1):
                stars = "⭐" * int(wine['quality'])
                aging_min = int(wine.get('aging_time', 0) // 60)
                wine_text += f"  [{idx}] {wine['name']} {stars} (品质{wine['quality']})\n"
                if aging_min > 0:
                    wine_text += f"      已陈酿 {aging_min} 分钟\n"
        else:
            wine_text += "  暂无酒品\n"
        
        coins_text = f"\n💰 金币：{user['coins']}"
        result = f"🎒 {user_name} 的背包\n\n{mat_text}{wine_text}{coins_text}"
        yield event.plain_result(result)

    @filter.command("配方列表")
    async def recipe_list(self, event: AstrMessageEvent):
        """查看所有酿酒配方"""
        recipes = self._get_all_recipes()
        
        cn_recipes = [(rid, r) for rid, r in recipes.items() if r['type'] == '国酒']
        en_recipes = [(rid, r) for rid, r in recipes.items() if r['type'] == '洋酒']
        
        text = "📜 酿酒配方大全\n\n"
        
        text += "🇨🇳 【国酒系列】\n"
        for rid, r in cn_recipes:
            stars = "⭐" * r.get('base_quality', 1)
            text += f"  {rid} - {r['name']} {stars}\n"
            text += f"      基础售价: {r.get('base_price', 0)} 金币\n"
        
        text += "\n🌍 【洋酒系列】\n"
        for rid, r in en_recipes:
            stars = "⭐" * r.get('base_quality', 1)
            text += f"  {rid} - {r['name']} {stars}\n"
            text += f"      基础售价: {r.get('base_price', 0)} 金币\n"
        
        text += "\n💡 发送 /配方 <配方ID> 查看详细材料和酿造时间"
        yield event.plain_result(text)

    @filter.command("配方")
    async def recipe_detail(self, event: AstrMessageEvent, recipe_id: str = None):
        """查看具体配方详情"""
        if not recipe_id:
            yield event.plain_result("❌ 请输入配方ID\n格式示例：/配方 101\n发送 /配方列表 可查看所有配方")
            return
        
        recipes = self._get_all_recipes()
        
        if recipe_id not in recipes:
            yield event.plain_result(f"❌ 找不到配方「{recipe_id}」\n发送 /配方列表 查看所有可用配方")
            return
        
        recipe = recipes[recipe_id]
        materials = recipe.get('materials', {})
        materials_price = self._get_materials_price()
        
        # 计算材料总成本
        total_cost = 0
        mat_text = ""
        for mid, count in materials.items():
            if count <= 0:
                continue
            name = MATERIAL_NAMES.get(mid, mid)
            price = materials_price.get(mid, 0)
            cost = price * count
            total_cost += cost
            mat_text += f"  {name} x{count} (单价{price}金币) = {cost}金币\n"
        
        brew_time = recipe.get('brew_time', 60)
        base_price = recipe.get('base_price', 0)
        base_quality = recipe.get('base_quality', 1)
        aging_bonus = recipe.get('aging_bonus', 0.3)
        stars = "⭐" * base_quality
        
        text = f"""📖 配方详情：{recipe['name']}
分类：{recipe['type']}
配方ID：{recipe_id}
基础品质：{stars} ({base_quality}星)
酿造时间：{brew_time} 秒
基础售价：{base_price} 金币
陈酿加成：每周期 +{aging_bonus} 星

🧪 所需材料：
{mat_text}
💵 材料总成本：{total_cost} 金币

💡 利润分析：
  基础利润：{base_price - total_cost} 金币
  陈酿后售价更高，利润更丰厚！"""
        
        yield event.plain_result(text)

    @filter.command("酿酒市场")
    async def market(self, event: AstrMessageEvent):
        """查看材料市场价格"""
        prices = self._get_materials_price()
        
        text = "🛒 材料市场 - 今日价格\n\n"
        for mid, price in prices.items():
            name = MATERIAL_NAMES.get(mid, mid)
            text += f"  {name}: {price} 金币/份\n"
        
        text += "\n💡 发送 /酿酒购买 <材料名> <数量> 购买材料"
        yield event.plain_result(text)

    @filter.command("酿酒购买")
    async def buy_material(self, event: AstrMessageEvent, material: str = None, amount: str = None):
        """购买酿酒材料"""
        if material is None or amount is None:
            yield event.plain_result("❌ 指令格式错误\n正确格式：/酿酒购买 <材料名> <数量>\n示例：/酿酒购买 高粱 5\n发送 /酿酒市场 查看可购买材料列表")
            return
        
        # 数量格式校验
        try:
            amount = int(amount)
        except ValueError:
            yield event.plain_result("❌ 数量必须是数字，请重新输入\n示例：/酿酒购买 高粱 5")
            return
        
        if amount <= 0:
            yield event.plain_result("❌ 购买数量必须大于0")
            return
        
        # 支持中文材料名，转换为内部ID
        material_id = MATERIAL_IDS.get(material, material)
        
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
        user = self._get_user(user_id, user_name)
        
        prices = self._get_materials_price()
        
        if material_id not in prices:
            yield event.plain_result(f"❌ 材料「{material}」不存在\n发送 /酿酒市场 查看所有可购买材料")
            return
        
        price = prices[material_id]
        total_cost = price * amount
        
        if user['coins'] < total_cost:
            yield event.plain_result(f"❌ 金币不足！\n需要 {total_cost} 金币，你只有 {user['coins']} 金币")
            return
        
        # 扣款并增加材料
        user['coins'] -= total_cost
        user['materials'] = user.get('materials', {})
        user['materials'][material_id] = user['materials'].get(material_id, 0) + amount
        self._save_users()
        
        material_name = MATERIAL_NAMES.get(material_id, material)
        yield event.plain_result(f"""✅ 购买成功！
购买：{material_name} x{amount}
单价：{price} 金币
总价：{total_cost} 金币
剩余金币：{user['coins']}""")

    @filter.command("开始酿造")
    async def start_brewing(self, event: AstrMessageEvent, recipe_id: str = None):
        """开始酿造酒"""
        if not recipe_id:
            yield event.plain_result("❌ 请输入配方ID\n格式示例：/开始酿造 101\n发送 /配方列表 查看所有配方")
            return
        
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
        user = self._get_user(user_id, user_name)
        
        # 检查是否正在酿造
        if user.get('brewing'):
            yield event.plain_result("❌ 你正在酿造中，请等待完成后再开始新的酿造\n发送 /酿造状态 查看进度")
            return
        
        recipes = self._get_all_recipes()
        if recipe_id not in recipes:
            yield event.plain_result(f"❌ 配方「{recipe_id}」不存在\n发送 /配方列表 查看所有可用配方")
            return
        
        recipe = recipes[recipe_id]
        materials_needed = recipe.get('materials', {})
        user_materials = user.get('materials', {})
        
        # 检查材料是否足够
        missing = []
        for mid, need in materials_needed.items():
            if need <= 0:
                continue
            have = user_materials.get(mid, 0)
            if have < need:
                name = MATERIAL_NAMES.get(mid, mid)
                missing.append(f"{name}(缺{need-have}份)")
        
        if missing:
            yield event.plain_result(f"❌ 材料不足！缺少：{', '.join(missing)}\n发送 /酿酒市场 购买材料")
            return
        
        # 扣除材料
        for mid, need in materials_needed.items():
            if need > 0:
                user['materials'][mid] -= need
        
        # 开始酿造
        brew_time = recipe.get('brew_time', 60)
        now = time.time()
        user['brewing'] = {
            'recipe_id': recipe_id,
            'name': recipe['name'],
            'start_time': now,
            'end_time': now + brew_time,
        }
        self._save_users()
        
        yield event.plain_result(f"""🍶 开始酿造 {recipe['name']}！
酿造时间：{brew_time} 秒
预计完成：{time.strftime('%H:%M:%S', time.localtime(now + brew_time))}

发送 /酿造状态 查看实时进度
酿造完成后自动存入背包""")

    @filter.command("酿造状态")
    async def brewing_status(self, event: AstrMessageEvent):
        """查看酿造进度"""
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
        user = self._get_user(user_id, user_name)
        
        brewing = user.get('brewing')
        if not brewing:
            yield event.plain_result("ℹ️ 你当前没有在酿造的酒\n发送 /开始酿造 <配方ID> 开始酿酒")
            return
        
        now = time.time()
        end_time = brewing['end_time']
        remaining = max(0, int(end_time - now))
        total = int(end_time - brewing['start_time'])
        elapsed = total - remaining
        percent = int((elapsed / total) * 100) if total > 0 else 100
        progress_bar = "█" * (percent // 5) + "░" * (20 - percent // 5)
        
        yield event.plain_result(f"""⏳ 正在酿造：{brewing['name']}
进度：[{progress_bar}] {percent}%
剩余时间：{remaining} 秒
预计完成：{time.strftime('%H:%M:%S', time.localtime(end_time))}""")

    @filter.command("出售")
    async def sell_wine(self, event: AstrMessageEvent, index: str = None):
        """出售酒获得金币（按背包序号）"""
        if index is None:
            yield event.plain_result("❌ 请输入背包序号\n格式示例：/出售 1\n发送 /酿酒背包 查看你的酒品库存")
            return
        
        try:
            index = int(index)
        except ValueError:
            yield event.plain_result("❌ 序号必须是数字，请重新输入\n示例：/出售 1")
            return
        
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
        user = self._get_user(user_id, user_name)
        
        inventory = user.get('inventory', [])
        if not inventory:
            yield event.plain_result("❌ 你的背包里没有酒可以出售")
            return
        
        if index < 1 or index > len(inventory):
            yield event.plain_result(f"❌ 序号无效，背包共有 {len(inventory)} 瓶酒")
            return
        
        wine = inventory[index - 1]
        recipes = self._get_all_recipes()
        recipe = recipes.get(wine['recipe_id'], {})
        
        # 计算售价：基础价 * (品质 / 基础品质) * 1.2
        base_price = recipe.get('base_price', 100)
        base_quality = recipe.get('base_quality', 1)
        quality_multiplier = wine['quality'] / base_quality if base_quality > 0 else 1
        sell_price = int(base_price * quality_multiplier * 1.2)
        
        # 执行出售
        user['coins'] += sell_price
        user['total_earned'] = user.get('total_earned', 0) + sell_price
        inventory.pop(index - 1)
        self._save_users()
        
        stars = "⭐" * int(wine['quality'])
        yield event.plain_result(f"""💰 出售成功！
酒品：{wine['name']} {stars}
品质：{wine['quality']} 星
售价：{sell_price} 金币
当前金币：{user['coins']}
累计收益：{user['total_earned']} 金币""")

    @filter.command("酒窖")
    async def cellar(self, event: AstrMessageEvent):
        """查看酒窖状态"""
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
        user = self._get_user(user_id, user_name)
        
        max_slots = self.config.get('aging', {}).get('cellar_slots', 3)
        cellar = user.get('cellar', [])
        
        # 清理异常槽位
        invalid_count = 0
        for idx in range(len(cellar)-1, -1, -1):
            if 'wine' not in cellar[idx] or not cellar[idx]['wine']:
                cellar.pop(idx)
                invalid_count += 1
        if invalid_count > 0:
            self._save_users()
        
        text = f"🏺 我的酒窖 ({len(cellar)}/{max_slots} 槽位)\n\n"
        
        if not cellar:
            text += "  酒窖空空如也~ 放入酒品开始陈酿吧！\n"
        else:
            cycle = self.config.get('aging', {}).get('aging_cycle', 300)
            for idx, slot in enumerate(cellar, 1):
                wine = slot.get('wine')
                elapsed = int(time.time() - slot['start_time'])
                next_bonus = cycle - (elapsed % cycle)
                stars = "⭐" * int(wine['quality'])
                
                text += f"  [{idx}] {wine['name']} {stars}\n"
                text += f"      当前品质: {wine['quality']}星 | 已陈酿: {elapsed//60}分钟\n"
                text += f"      下次品质提升: {next_bonus}秒后\n"
        
        text += "\n💡 指令：\n"
        text += "  /入窖 <背包序号> - 将酒放入酒窖陈酿\n"
        text += "  /出窖 <酒窖序号> - 取出陈酿中的酒"
        
        yield event.plain_result(text)

    @filter.command("入窖")
    async def put_in_cellar(self, event: AstrMessageEvent, index: str = None):
        """将酒放入酒窖陈酿"""
        if index is None:
            yield event.plain_result("❌ 请输入背包序号\n格式示例：/入窖 1\n发送 /酿酒背包 查看你的酒品库存")
            return
        
        try:
            index = int(index)
        except ValueError:
            yield event.plain_result("❌ 序号必须是数字，请重新输入\n示例：/入窖 1")
            return
        
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
        user = self._get_user(user_id, user_name)
        
        inventory = user.get('inventory', [])
        cellar = user.get('cellar', [])
        max_slots = self.config.get('aging', {}).get('cellar_slots', 3)
        
        if len(cellar) >= max_slots:
            yield event.plain_result(f"❌ 酒窖已满（{max_slots}槽位），请先取出一些酒")
            return
        
        if index < 1 or index > len(inventory):
            yield event.plain_result(f"❌ 背包序号无效，共有 {len(inventory)} 瓶酒")
            return
        
        # 从背包移除，存入酒窖
        wine = inventory.pop(index - 1)
        cellar.append({
            "wine": wine,
            "start_time": time.time(),
        })
        user['cellar'] = cellar
        self._save_users()
        
        stars = "⭐" * int(wine['quality'])
        yield event.plain_result(f"""✅ 已放入酒窖陈酿！
酒品：{wine['name']} {stars}
当前品质：{wine['quality']} 星
陈酿开始时间：{time.strftime('%H:%M:%S')}

酒窖会自动提升酒的品质，放得越久品质越高，售价越贵！""")

    @filter.command("出窖")
    async def take_out_cellar(self, event: AstrMessageEvent, index: str = None):
        """从酒窖取出酒"""
        if index is None:
            yield event.plain_result("❌ 请输入酒窖序号\n格式示例：/出窖 1\n发送 /酒窖 查看陈酿中的酒品")
            return
        
        try:
            index = int(index)
        except ValueError:
            yield event.plain_result("❌ 序号必须是数字，请重新输入\n示例：/出窖 1")
            return
        
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
        user = self._get_user(user_id, user_name)
        
        cellar = user.get('cellar', [])
        
        if index < 1 or index > len(cellar):
            yield event.plain_result(f"❌ 酒窖序号无效，共有 {len(cellar)} 瓶酒在陈酿")
            return
        
        slot = cellar.pop(index - 1)
        wine = slot['wine']
        # 放回背包
        user['inventory'].append(wine)
        self._save_users()
        
        stars = "⭐" * int(wine['quality'])
        yield event.plain_result(f"""✅ 已取出酒品！
{wine['name']} {stars}
当前品质：{wine['quality']} 星
累计陈酿：{int(wine.get('aging_time', 0)//60)} 分钟

已放回背包，可继续陈酿或出售""")

    @filter.command("富豪榜")
    async def coins_ranking(self, event: AstrMessageEvent):
        """金币排行榜"""
        sorted_users = sorted(
            self.users.items(),
            key=lambda x: x[1].get('coins', 0),
            reverse=True
        )[:10]
        
        text = "🏆 富豪排行榜 TOP 10\n\n"
        
        medals = ["🥇", "🥈", "🥉"]
        for idx, (uid, udata) in enumerate(sorted_users, 1):
            medal = medals[idx-1] if idx <= 3 else f"  {idx}."
            name = udata.get('name', uid)
            coins = udata.get('coins', 0)
            text += f"{medal} {name} - {coins} 金币\n"
        
        if not sorted_users:
            text += "  暂无排行数据，快来成为第一位酿酒大师吧！\n"
        
        yield event.plain_result(text)

    @filter.command("酿酒大师榜")
    async def brew_ranking(self, event: AstrMessageEvent):
        """酿酒数量排行榜"""
        sorted_users = sorted(
            self.users.items(),
            key=lambda x: x[1].get('total_brewed', 0),
            reverse=True
        )[:10]
        
        text = "🏆 酿酒大师排行榜 TOP 10\n\n"
        
        medals = ["🥇", "🥈", "🥉"]
        for idx, (uid, udata) in enumerate(sorted_users, 1):
            medal = medals[idx-1] if idx <= 3 else f"  {idx}."
            name = udata.get('name', uid)
            count = udata.get('total_brewed', 0)
            earned = udata.get('total_earned', 0)
            text += f"{medal} {name} - 酿酒{count}瓶 | 累计收益{earned}金币\n"
        
        if not sorted_users:
            text += "  暂无排行数据，快来酿造你的第一瓶美酒吧！\n"
        
        yield event.plain_result(text)

    async def terminate(self):
        """插件卸载时清理资源，保存数据"""
        if hasattr(self, '_aging_task') and self._aging_task:
            self._aging_task.cancel()
        self._save_users()
        logger.info("[酿酒大师] 插件已卸载，所有数据已保存")