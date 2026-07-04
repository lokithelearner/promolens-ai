#!/usr/bin/env bash
cd /sessions/fervent-dazzling-cray/mnt/PromoLens/promolens/record
ffmpeg -y -f concat -safe 0 -i list.txt -i "/sessions/fervent-dazzling-cray/mnt/PromoLens/ElevenLabs_2026-06-09T17_39_16_Roger - Laid-Back, Casual, Resonant_pre_sp100_s50_sb75_se0_b_m2.mp3"  -filter_complex "[0:v]fps=24,scale=1280:720,format=yuv420p,subtitles=captions.srt:force_style='FontName=DejaVu Sans,Fontsize=18,PrimaryColour=&H00FFFFFF&,BackColour=&HA0000000&,BorderStyle=3,Outline=0,Shadow=0,MarginV=26,Alignment=2'[v];[1:a]adelay=3000|3000[a]"  -map "[v]" -map "[a]" -shortest -c:v libx264 -preset ultrafast -crf 23 -pix_fmt yuv420p -c:a aac -b:a 160k  -movflags +faststart /sessions/fervent-dazzling-cray/mnt/PromoLens/PromoLens_AI_Demo.mp4
echo "ENCODE_EXIT $?" >> enc.log
