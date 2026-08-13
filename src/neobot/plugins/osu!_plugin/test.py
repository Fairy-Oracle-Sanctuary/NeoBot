from ossapi import Ossapi

# 初始化客户端（替换为自己的client_id和client_secret）
api = Ossapi("49746", "")

# 根据用户名查询用户信息
print(api.user("[PAW]K2CRO4"))
# 根据用户ID查询osu模式下的用户信息
print(api.user(12092800, mode="osu").username)
# 查询指定谱面的ID
print(api.beatmap(221777).id)