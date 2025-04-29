# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

import os
import sys

# 获取虚拟环境的site-packages路径
if sys.platform.startswith('win'):
    venv_site_packages = '.venv/Lib/site-packages'
    yutto_exe = os.path.join(os.getcwd(), '.venv', 'Scripts', 'yutto.exe')
else:  # Linux/macOS
    python_version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    venv_site_packages = f'.venv/lib/{python_version}/site-packages'
    yutto_exe = os.path.join(os.getcwd(), '.venv', 'bin', 'yutto')

# 检查yutto可执行文件
if not os.path.exists(yutto_exe):
    print(f"警告: 找不到 yutto: {yutto_exe}")
    if os.name == 'nt':  # Windows
        # 尝试查找yutto.exe
        import glob
        yutto_candidates = glob.glob(os.path.join('.venv', '**', 'yutto.exe'), recursive=True)
        if yutto_candidates:
            yutto_exe = yutto_candidates[0]
            print(f"找到替代的yutto.exe: {yutto_exe}")
    else:  # Linux/macOS
        # 尝试查找yutto
        import glob
        yutto_candidates = glob.glob(os.path.join('.venv', '**', 'yutto'), recursive=True)
        if yutto_candidates:
            yutto_exe = yutto_candidates[0]
            print(f"找到替代的yutto: {yutto_exe}")

# 设置平台相关的路径分隔符
path_sep = ';' if sys.platform.startswith('win') else ':'

a = Analysis(
    ['app_launcher.py'],
    pathex=[],
    binaries=[
        (yutto_exe, '.'),
    ],
    datas=[
        ('config/*', 'config'),
        ('scripts', 'scripts'),
        ('routers', 'routers'),
        ('main.py', '.'),
        (os.path.join(venv_site_packages, 'pyecharts/datasets'), 'pyecharts/datasets'),
        (os.path.join(venv_site_packages, 'pyecharts/render/templates'), 'pyecharts/render/templates'),
        (os.path.join(venv_site_packages, 'yutto'), 'yutto'),
        # 添加requirements.txt中所有依赖的相关模块
        (os.path.join(venv_site_packages, 'uvicorn'), 'uvicorn'),
        (os.path.join(venv_site_packages, 'fastapi'), 'fastapi'),
        (os.path.join(venv_site_packages, 'qrcode'), 'qrcode'),
        (os.path.join(venv_site_packages, 'requests'), 'requests'),
        (os.path.join(venv_site_packages, 'jieba'), 'jieba'),
        (os.path.join(venv_site_packages, 'pydantic'), 'pydantic'),
        (os.path.join(venv_site_packages, 'numpy'), 'numpy'),
        (os.path.join(venv_site_packages, 'sklearn'), 'sklearn'),
        (os.path.join(venv_site_packages, 'scikit_learn-1.5.2.dist-info'), 'scikit_learn-1.5.2.dist-info'),
        (os.path.join(venv_site_packages, 'snownlp'), 'snownlp'),
        (os.path.join(venv_site_packages, 'yaml'), 'yaml'),
        (os.path.join(venv_site_packages, 'schedule'), 'schedule'),
        (os.path.join(venv_site_packages, 'pandas'), 'pandas'),
        (os.path.join(venv_site_packages, 'openpyxl'), 'openpyxl'),
        (os.path.join(venv_site_packages, 'pymysql'), 'pymysql'),
        (os.path.join(venv_site_packages, 'urllib3'), 'urllib3'),
        (os.path.join(venv_site_packages, 'httpx'), 'httpx'),
        (os.path.join(venv_site_packages, 'aiohttp'), 'aiohttp'),
        (os.path.join(venv_site_packages, 'jinja2'), 'jinja2'),
        (os.path.join(venv_site_packages, 'pyecharts'), 'pyecharts'),
        (os.path.join(venv_site_packages, 'PIL'), 'PIL'),
        (os.path.join(venv_site_packages, 'yutto'), 'yutto'),
        (os.path.join(venv_site_packages, 'dateutil'), 'dateutil'),
        (os.path.join(venv_site_packages, 'psutil'), 'psutil'),
        (os.path.join(venv_site_packages, 'tqdm'), 'tqdm'),
        (os.path.join(venv_site_packages, 'email_validator'), 'email_validator'),
        (os.path.join(venv_site_packages, 'loguru'), 'loguru'),
    ],
    hiddenimports=[
        'fastapi',
        'fastapi.middleware',
        'fastapi.middleware.cors',
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'pydantic',
        'scripts',
        'routers',
        'numpy',
        'pandas',
        'PIL',
        'jieba',
        'main',
        'asyncio',
        'starlette',
        'starlette.middleware',
        'starlette.middleware.cors',
        'jinja2.ext',
        'scipy',
        'pyecharts',
        'pyecharts.charts',
        'pyecharts.components',
        'pyecharts.options',
        'pyecharts.globals',
        'pyecharts.commons.utils',
        'pyecharts.charts.basic_charts.bar',
        'pyecharts.charts.basic_charts.pie',
        'pyecharts.charts.basic_charts.line',
        'pyecharts.charts.basic_charts.scatter',
        'pyecharts.charts.basic_charts.heatmap',
        'pyecharts.charts.basic_charts.funnel',
        'pyecharts.charts.basic_charts.effectscatter',
        'pyecharts.charts.composite_charts.page',
        'pyecharts.charts.composite_charts.timeline',
        'pyecharts.charts.composite_charts.grid',
        'starlette.middleware',
        'starlette.middleware.cors',
        'starlette.types',
        'starlette.routing',
        'starlette.websockets',
        'scipy.special.cython_special',
        'scipy.sparse.csgraph._validation',
        # requirements.txt中所有依赖
        'qrcode',
        'requests',
        'jieba',
        'pydantic',
        'numpy',
        'sklearn',
        'sklearn.cluster',
        'sklearn.cluster.k_means_',
        'sklearn.utils',
        'sklearn.utils.extmath',
        'sklearn.preprocessing',
        'sklearn.metrics',
        'snownlp',
        'yaml',
        'schedule',
        'pandas',
        'openpyxl',
        'pymysql',
        'urllib3',
        'httpx',
        'aiohttp',
        'jinja2',
        'pyecharts',
        'PIL',
        'yutto',
        'dateutil',
        'psutil',
        'tqdm',
        'email_validator',
        'loguru',
        # 以下是fastapi和其他库的子模块
        'fastapi.applications',
        'fastapi.routing',
        'fastapi.responses',
        'fastapi.exceptions',
        'fastapi.encoders',
        'fastapi.utils',
        'fastapi.openapi',
        'fastapi.staticfiles',
        'fastapi.websockets',
        'fastapi.background',
        'fastapi.concurrency',
        'fastapi.security',
        'fastapi.dependency',
        'fastapi.params',
        'python-dateutil',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch',
        'torchaudio',
        'torchvision',
        'faster_whisper',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BilibiliHistoryAnalyzer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BilibiliHistoryAnalyzer',
)