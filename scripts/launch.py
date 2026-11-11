import sys

if "--smoke-test" in sys.argv:
    from fps_tools.smoke import smoke
    raise SystemExit(smoke(sys.argv[sys.argv.index("--smoke-test") + 1]))

from fps_tools.studio import main

raise SystemExit(main())
