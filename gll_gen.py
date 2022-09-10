
from __future__ import print_function
from ast import Import

import argparse
import os
import re

try:
    import urllib.request as urllib2
except ImportError:
    import urllib2

EXT_SUFFIX = ['ARB', 'EXT', 'KHR', 'OVR', 'NV', 'AMD', 'INTEL']

def is_ext(proc):
    return any(proc.endswith(suffix) for suffix in EXT_SUFFIX)

def write(f, s):
    f.write(s.encode('utf-8'))

def touch_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def download(url, dst):
    if os.path.exists(dst):
        print("Reusing {0}...".format(dst))
        return
    
    print("Downloading {0}...".format(dst))
    web = urllib2.urlopen(urllib2.Request(url, headers={'User-Agent': 'Mozilla/5.0'}))
    with open(dst, 'wb') as f:
        f.writelines(web.readlines())

# --------------------------------------------------------------
# Parse arguements
# --------------------------------------------------------------

parser = argparse.ArgumentParser(description='gll generator script')
parser.add_argument('--ext', action='store_true', help='Load extensions')
parser.add_argument('--root', type=str, default='', help='Root directory')
args = parser.parse_args()

# --------------------------------------------------------------
# Create directories
# --------------------------------------------------------------

touch_dir(os.path.join(args.root, 'include/GL'))
touch_dir(os.path.join(args.root, 'include/KHR'))
touch_dir(os.path.join(args.root, 'src'))

# --------------------------------------------------------------
# Download glcorearb.h & khrplatform.h
# --------------------------------------------------------------

download("https://www.khronos.org/registry/OpenGL/api/GL/glcorearb.h",
         os.path.join(args.root, 'include/GL/glcorearb.h'))

download("https://www.khronos.org/registry/EGL/api/KHR/khrplatform.h",
         os.path.join(args.root, 'include/KHR/khrplatform.h'))

# --------------------------------------------------------------
# Parse glcorearb.h
# --------------------------------------------------------------

print("Parsing glcorearb.h header...")
procs = []
p = re.compile(r'GLAPI.*APIENTRY\s+(\w+)')
with open(os.path.join(args.root, 'include/GL/glcorearb.h'), 'r') as f:
    for line in f:
        m = p.match(line)
        if not m:
            continue
        
        proc = m.group(1)
        if args.ext or not is_ext(proc):
            procs.append(proc)

procs.sort()

# --------------------------------------------------------------
# Generate gll.h
# --------------------------------------------------------------

print("Generating {0}...".format(os.path.join(args.root, "include/GL/gll.h")))
with open(os.path.join(args.root, "include/GL/gll.h"), "wb") as f:
    write(f, r'''#ifndef __gll_h__
#define __gll_h__

#include <GL/glcorearb.h>

#ifndef GLLAPI
#define GLLAPI
#endif

#ifndef __gl_h_
#define __gl_h_
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef void    (* GLLglproc)(void);
typedef void*   (* GLLloadproc)(const char*);

GLLAPI void gllLoadGL(void);
GLLAPI void gllLoadGLLoader(GLLloadproc loadProc);
GLLAPI GLLglproc gllGetProcAddress(const char* procName);

''')

    for proc in procs:
        write(f, 'extern {0: <55} __gll_{1};\n'.format('PFN{0}PROC'.format(proc.upper()), proc))

    write(f, '\n')

    for proc in procs:
        write(f, '#define {0: <48} __gll_{0}\n'.format(proc))

    write(f, r'''
#ifdef __cplusplus
}
#endif

#endif
''')

# --------------------------------------------------------------
# Generate gll.c
# --------------------------------------------------------------

print("Generating {0}...".format(os.path.join(args.root, 'src/gll.c')))

with (open(os.path.join(args.root, 'src/gll.c'), 'wb')) as f:
    write(f, r'''#include <GL/gll.h>

#include <stdlib.h>

#define ARRAY_SIZE(x) (sizeof((x)) / sizeof((x)[0]))

#if defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN 1
#endif
#include <Windows.h>

static HMODULE libgl;
typedef PROC (__stdcall* GLLglGetProcAddr)(LPCSTR);
static GLLglGetProcAddr gll_wglGetProcAddress;

static int open_libgl(void) {
    libgl = LoadLibraryA("opengl32.dll");
    if (!libgl) {
        return 1;
    }

    gll_wglGetProcAddress = (GLLglGetProcAddr)GetProcAddress(libgl, "wglGetProcAddress");

    return 0;
}

static void close_libgl(void) {
    FreeLibrary(libgl);
}

static GLLglproc get_proc(const char* procName) {
    GLLglproc proc;

    proc = (GLLglproc)gll_wglGetProcAddress(procName);
    if (!proc) {
        proc = (GLLglproc)GetProcAddress(libgl, procName);
    }

    return proc;
}

#elif defined(__APPLE__)
#include <dlfcn.h>

static void* libgl;

static int open_libgl(void) {
    libgl = dlopen("/System/Library/Frameworks/OpenGL.framework/OpenGL", RTLD_LAZY | RTLD_LOCAL);
    if (!libgl) {
        return 1;
    }

    return 0;
}

static void close_libgl(void) {
    dlclose(libgl);
}

static GLLglproc get_proc(const char* procName) {
    GLLglproc proc;

    *(void**)(&proc) = dlsym(libgl, procName);

    return proc;
}

#else
#include <dlfcn.h>

static void* libgl;     /* OpenGL */
static void* libglx;    /* GLX */
static void* libegl;    /* EGL */

static GLLloadproc gll_glGetProcAddress;

static void close_libgl(void) {
    if (libgl) {
        dlclose(libgl);
        libgl = NULL;
    }
    if (libegl) {
        dlclose(libegl);
        libegl = NULL;
    }
    if (libglx) {
        dlclose(libglx);
        libglx = NULL;
    }
}

static int is_lib_loaded(const char* name, void** lib) {
    *lib = dlopen(name, RTLD_LAZY | RTLD_LOCAL | RTLD_NOLOAD);
    return *lib != NULL;
}

static int open_libs(void) {
    if (is_lib_loaded("libEGL.so.1", &libegl) ||
        is_lib_loaded("libGLX.so.1", &libglx)) {
        libgl = dlopen("libOpenGL.so.0", RTLD_LAZY | RTLD_LOCAL);
        if (libgl) {
            return 0;
        }
        else {
            close_libgl();
        }
    }

    if (is_lib_loaded("libGL.so.1", &libgl))
        return 0;

    libgl = dlopen("libOpenGL.so.0", RTLD_LAZY | RTLD_LOCAL);
    libegl = dlopen("libEGL.so.1", RTLD_LAZY | RTLD_LOCAL);
    if (libgl && libegl) {
        return 0;
    }

    close_libgl();

    libgl = dlopen("libGL.so.1", RTLD_LAZY | RTLD_LOCAL);
    if (libgl) {
        return 0;
    }

    return 1;
}

static int open_libgl(void) {
    int r = open_libs();
    if (r) {
        return r;
    }

    if (libegl) {
        *(void**)(&gll_glGetProcAddress) = dlsym(libegl, "eglGetProcAddress");
    }
    else if (libglx) {
        *(void**)(&gll_glGetProcAddress) = dlsym(libegl, "glXGetProcAddressARB");
    }
    else {
        *(void**)(&gll_glGetProcAddress) = dlsym(libgl, "glXGetProcAddressARB");
    }

    if (!gll_glGetProcAddress) {
        close_libgl();
        return 1;
    }

    return 0;
}

static GLLglproc get_proc(const char* procName) {
    GLLglproc proc = NULL;

    if (libegl) {
        *(void**)(&proc) = dlsym(libgl, procName);
    }

    if (!proc) {
        proc = gll_glGetProcAddress(procName);
    }

    if (!libegl && !proc) {
        *(void**)(&proc) = dlsym(libgl, procName);
    }

    return proc;
}

#endif

static void load_procs(GLLloadproc loadProc);

void gllLoadGL(void) {
    int r = 0;

    r = open_libgl();
    if (r) {
        return r;
    }

    atexit(close_libgl);

    return gllLoadGLLoader(get_proc);
}

void gllLoadGLLoader(GLLloadproc loadProc) {
    loadProcs(loadProc);
}

GLLglproc gllGetProcAddress(const char* procName) {
    return get_proc(procName);
}

''')

    for proc in procs:
        write(f, '{0: <55} __gll_{1};\n'.format('PFN{0}PROC'.format(proc.upper()), proc))

    write(f, r'''
static void load_procs(GLLloadproc loadProc) {''')

    for proc in procs:
        write(f, r'''
    __gll_{0} =
        ({1})loadProc("{0}");
'''.format(proc, 'PFN{0}PROC'.format(proc.upper())))

    write(f, r'''}''');
