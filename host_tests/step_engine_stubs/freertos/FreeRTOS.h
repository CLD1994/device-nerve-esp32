#pragma once
#include <assert.h>
typedef int portMUX_TYPE;
#define portMUX_INITIALIZER_UNLOCKED 0
extern int step_test_lock_depth;
#define portENTER_CRITICAL(l) do { (void)(l); assert(step_test_lock_depth==0); step_test_lock_depth=1; } while(0)
#define portEXIT_CRITICAL(l) do { (void)(l); assert(step_test_lock_depth==1); step_test_lock_depth=0; } while(0)
#define portENTER_CRITICAL_ISR(l) portENTER_CRITICAL(l)
#define portEXIT_CRITICAL_ISR(l) portEXIT_CRITICAL(l)
