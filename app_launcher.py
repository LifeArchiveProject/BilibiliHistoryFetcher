import os
import sys
from multiprocessing import freeze_support

import uvicorn


def main():
    try:
        # 添加项目根目录到 Python 路径
        if getattr(sys, 'frozen', False):
            # 如果是打包后的exe运行
            base_path = os.path.dirname(sys.executable)
            internal_path = os.path.join(base_path, '_internal')
            # 确保 _internal 目录在 Python 路径的最前面
            sys.path.insert(0, internal_path)
            sys.path.insert(0, base_path)
            
            # 检查 main.py 的位置
            main_path = os.path.join(internal_path, 'main.py')  # 修改这里，在 _internal 目录中查找
            if not os.path.exists(main_path):
                raise FileNotFoundError(f"找不到 main.py: {main_path}")
        else:
            # 如果是直接运行python脚本
            base_path = os.path.dirname(os.path.abspath(__file__))
            sys.path.insert(0, base_path)
        
        # 打印当前环境信息
        print("\n=== 环境信息 ===")
        print(f"当前工作目录: {os.getcwd()}")
        print(f"可执行文件目录: {os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else '非打包环境'}")
        print(f"Python 路径: {sys.path}")
        print(f"是否为打包环境: {getattr(sys, 'frozen', False)}")
        
        # 检查各个重要目录和文件
        important_items = [
            ('当前目录', os.getcwd()),
            ('可执行文件目录', base_path),
            ('_internal目录', internal_path if getattr(sys, 'frozen', False) else None),
            ('main.py位置', main_path if getattr(sys, 'frozen', False) else None),
            ('output目录', os.path.join(base_path, 'output')),
        ]
        
        print("\n=== 目录和文件检查 ===")
        for name, path in important_items:
            if path:
                print(f"\n{name}: {path}")
                print(f"存在: {os.path.exists(path)}")
                if os.path.exists(path):
                    if os.path.isdir(path):
                        print(f"目录内容: {os.listdir(path)}")
                    else:
                        print("这是一个文件")
        print("===============\n")
        
        # 启用多进程支持
        freeze_support()
        
        print("正在启动服务器...")
        print("API文档:http://0.0.0.0:8899/docs")
        
        # 启动FastAPI应用
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=8899,
            reload=False
        )
    except Exception as e:
        print("\n=== 发生错误 ===")
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {str(e)}")
        print("\n完整错误信息:")
        import traceback
        traceback.print_exc()
        print("\n=== 调试信息 ===")
        print(f"当前目录内容: {os.listdir(os.getcwd())}")
        if getattr(sys, 'frozen', False):
            internal_path = os.path.join(os.getcwd(), '_internal')
            if os.path.exists(internal_path):
                print(f"_internal 目录内容: {os.listdir(internal_path)}")
        print("===============\n")

def run():
    try:
        main()
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        print(f"\n程序异常退出: {e}")
    finally:
        print("\n=== 程序已停止运行 ===")
        print("按任意键退出...")
        # 等待任意键输入
        if os.name == 'nt':  # Windows
            os.system('pause >nul')
        else:  # Linux/Mac
            try:
                import termios
                import tty
                def getch():
                    fd = sys.stdin.fileno()
                    old_settings = termios.tcgetattr(fd)
                    try:
                        tty.setraw(sys.stdin.fileno())
                        ch = sys.stdin.read(1)
                    finally:
                        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                    return ch
                getch()
            except ImportError:
                input()

if __name__ == '__main__':
    run()