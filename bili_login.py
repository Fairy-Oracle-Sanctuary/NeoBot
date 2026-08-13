import asyncio
from bilibili_api import login_v2

async def main():
    print("请使用 Bilibili 手机 App 扫描二维码登录")
    qr = login_v2.QrCodeLogin()
    demo = await qr.generate_qrcode()
    await print( qr.get_qrcode_terminal())
    
    print("登录成功！")
    print(f"sessdata = \"{credential.sessdata}\"")
    print(f"bili_jct = \"{credential.bili_jct}\"")
    print(f"buvid3 = \"{credential.buvid3}\"")
    print(f"dedeuserid = \"{credential.dedeuserid}\"")

if __name__ == '__main__':
    asyncio.run(main())
