#pragma once
#define ESP_RETURN_ON_ERROR(expr,tag,msg) do { int e_=(expr); if(e_!=ESP_OK)return e_; } while(0)
