# -*- coding: utf-8 -*-
"""
MCC 挂机点数据（来自玩家整理的挂机菜单）

结构：AFK_GROUPS = [{name, note, spots: [(显示名, 传送名, 备注)]}]
传送名以 "/" 开头时原样作为指令发送，否则拼成 "/res tp <传送名>"。
"""

# 挂机点分组数据
AFK_GROUPS = [
    {
        "name": "组织基地",
        "note": "组织自己的",
        "spots": [
            ("晚风二号基地【建筑无任何限制】", "wf", ""),
            ("晚风主城", "wf2", ""),
            (
                "晚风工业区",
                "wfiz",
                "机器清单：地毯机、竹子机、刷雪机、岩浆机、甘蔗机、自动农场、刷怪塔、"
                "仙人掌机、刷石机、铁轨机、21倍速&37倍速熔炉组、甘蔗农场、树脂机、黏土机、"
                "全自动石头平滑石工厂、640熔炉、作物机、树厂",
            ),
        ],
    },
    {
        "name": "地狱交通工程（U1）",
        "note": "",
        "spots": [
            ("晚风政府站（地狱传送点）", "U1_WFgoverment", ""),
            ("晚风海滩站+金门湾机场（地狱传送点）", "U1_haitan", ""),
            ("维特东站（地狱传送点）", "U1_Vivathr", ""),
        ],
    },
    {
        "name": "公共挂机点",
        "note": "",
        "spots": [
            ("晚风交易所", "wanfengcunmin", "已被组织基地覆盖，等待通车"),
            ("猪人塔", "wfzrt2-o", "别名 wfzrt2-n"),
            ("凋零玫瑰", "wfdlmg", ""),
            ("沼泽炸怪塔", "wfsgt", ""),
            ("三连骷髅", "wfdl", "别名 wfdlgj、wfdlsj"),
            ("交易所", "jy", "装备附魔比较全"),
            ("交易所", "SQJY", ""),
            ("烈焰人农场", "blaze", ""),
            ("刷沙机", "WFSand", ""),
            ("溺尸塔", "WFTrident", ""),
            ("海晶灯", "letsw", "墨囊鳕鱼海晶灯"),
            ("雪山", "xueshan", ""),
            ("陶瓦", "edi", ""),
            ("火药塔", "huoyaota", ""),
            ("刷铁机", None, ""),
            ("凋灵骷髅头", "diaolingtou", "产骨粉和煤炭"),
            ("杀雕机", "shadiaoji", ""),
            ("女巫塔", "nvwugj", "红石玻璃瓶火药木棍萤石粉瞬间恢复药水"),
            ("潜影贝", "wfbknc", ""),
            ("灾厄瓶", "jielue", "挂机 jieluegj"),
            ("小黑塔", "wfjyt", "已申请成为公用小黑塔"),
            ("炼药机", "wflyj", ""),
            ("猪肉塔", "wf-zhurouta-overworld", "下界挂机点 wf-zhurouta-xiajie"),
            ("染料/花", "huohai", "或 huahai"),
            ("唱片生产机器", "Earhuoyaota", "不要穿荆棘"),
            ("二号空置域", "WF-SQXK-520W", ""),
        ],
    },
    {
        "name": "已鼠之人的遗产",
        "note": "",
        "spots": [
            ("烈焰人", "diyulianyanrenshuaguailong", ""),
            ("青蛙灯", "yywmd", ""),
        ],
    },
    {
        "name": "公共设施",
        "note": "",
        "spots": [
            ("熊猫分类机与所有公共生电", "/warp gyq", "生电传送在一楼"),
            ("印钞机", "/res tp ycj", ""),
            ("刷怪塔", "lbssgt", ""),
            ("养老院公用猪人塔", "jin", "产金子"),
        ],
    },
    {
        "name": "群系领地",
        "note": "想要什么稀奇古怪的地形都可以找萧风（xiaofeng）",
        "spots": [
            ("挖珊瑚", "wfshanhu", ""),
            ("原始针叶林", "wfyuanshizhenyelin", ""),
            ("蘑菇岛", "wfwlmgd", ""),
            ("苍白树林", "wfcangbaizhiyuan", "地下繁茂和试炼"),
            ("红树林", "wfhslzz", ""),
            ("樱花", "wfyhsl", ""),
            ("樱花（更大）", "wfyhsl2", ""),
            ("试炼", "wfsl1", "上方有矿井；wfsl2 上方有前哨站；wfsl3~wfsl11"),
            ("草甸", "wfcaodian", ""),
            ("竹林", "wfzl", ""),
        ],
    },
]
