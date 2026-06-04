idf_component_register(
    SRCS "main.c" "aw9523b.c" "es8218e.c" "font_chip.c"
         "opus_codec.c" "xiaozhi_protocol.c" "audio_pipeline.c"
         "fmqtt_client.c"
    INCLUDE_DIRS "."
    REQUIRES nvs_flash esp_wifi driver esp_lcd json mqtt
)

# Link pre-compiled GT30L24A3W font chip library
target_link_libraries(${COMPONENT_LIB} INTERFACE ${CMAKE_CURRENT_SOURCE_DIR}/libGT30L24A3W.a)
