#!/usr/bin/env python3
"""Compile actual POLED1 format code with ESP uint32_t's unsigned-long spelling.

This is a host ABI-spelling regression, NOT an ESP-IDF target build. The host
long may be 64 bits; only printf's required variadic argument type is modeled.
"""
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
source = (ROOT / 'components/cartfsm/cartfsm.c').read_text()
start = source.index('#ifdef CONFIG_MAGNETIC_ENCODER_POLE_DIAGNOSTICS\nstatic void pole_diagnostic_point')
end = source.index('\nstatic void exec_tmc_trace_query', start)
body = source[start:end]
# Use production structures, replacing only uint32_t's host spelling.
header = (ROOT / 'components/magnetic_encoder/include/magnetic_encoder_diagnostic.h').read_text()
header = header.replace('#pragma once', '').replace('uint32_t', 'unsigned long')
preamble = r'''
#include <stdio.h>
#include <inttypes.h>
#undef PRIu32
#define PRIu32 "lu"
'''
stubs = r'''
static int s_output_lock, s_mode, s_fault_settling;
enum {CM_DISABLED,CM_FAULT,portMAX_DELAY};
static void xSemaphoreTake(int a,int b){(void)a;(void)b;}
static void xSemaphoreGive(int a){(void)a;}
static void cartproto_send_raw(const char *a,int b){(void)a;(void)b;}
static void cartproto_send_err(const char *a){(void)a;}
static bool poleang_diagnostic_get(me_diag_t *d){memset(d,0,sizeof(*d));return true;}
'''
with tempfile.TemporaryDirectory() as directory:
    path = pathlib.Path(directory) / 'format.c'
    path.write_text(preamble + header + stubs + body + '\nint main(void){exec_pole_diagnostic_query();return 0;}\n')
    # Disabled path intentionally leaves test stubs unused.
    for enabled in (0, 1):
        args = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wformat=2',
                '-Wno-unused-function', '-Wno-unused-variable']
        if enabled:
            args += ['-DCONFIG_MAGNETIC_ENCODER_POLE_DIAGNOSTICS=1']
        subprocess.run(args + ['-fsyntax-only', str(path)], check=True)
print('POLED1 unsigned-long typedef format regression passed (on/off; not target build)')
