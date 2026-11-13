#pragma once
#include <stdbool.h>
#include <stdint.h>
typedef enum { CMD_INVALID, CMD_INFO, CMD_STOP, CMD_RUN } command_kind;
typedef struct { command_kind kind; uint32_t hz, duration_ms; } probe_command;
typedef enum { PROBE_IDLE, PROBE_RUNNING, PROBE_FAULT } probe_state;
typedef enum { ACTION_NONE, ACTION_FEED, ACTION_STOP } probe_action;
typedef struct {
    probe_state state;
    uint64_t started, last_feed, last_seen, deadline;
    uint32_t hz;
    const char *reason;
} probe_control;
probe_command probe_parse(const char *line);
bool probe_start(probe_control *p, probe_command c, uint64_t now, bool en_high);
probe_action probe_tick(probe_control *p, uint64_t now, bool en_high);
void probe_stop(probe_control *p);
void probe_fault(probe_control *p, const char *reason);
