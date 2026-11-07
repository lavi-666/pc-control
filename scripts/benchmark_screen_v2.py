import os
import sys
import time
import json
import numpy as np
import av
from fractions import Fraction
from av.video.reformatter import Colorspace, ColorRange, Interpolation

def benchmark_encoders():
    print("=== 1. Hardware vs Software Encoder Latency Benchmark ===")
    width, height = 1920, 1080
    frames_count = 60
    
    # Generate realistic synthetic desktop frames (solid colors, high-contrast text-like edges)
    frames = []
    for i in range(frames_count):
        arr = np.zeros((height, width, 3), dtype=np.uint8)
        # Background dark grey
        arr[:] = (24, 24, 27)
        # Accent boxes
        arr[100:300, 200:800] = (59, 130, 246)
        # Moving bar
        x_pos = (i * 25) % (width - 100)
        arr[500:600, x_pos:x_pos+100] = (239, 68, 68)
        # Fine text-like grid lines
        arr[700:900:4, 100:1800] = (255, 255, 255)
        frames.append(arr)
        
    results = {}
    
    # Test candidates
    test_configs = [
        ("Old Baseline: libx264 Ultrafast Baseline", "libx264", {"preset": "ultrafast", "tune": "zerolatency", "profile": "baseline"}, 4_500_000),
        ("New Sunshine NVENC: Low-Latency High Profile", "h264_nvenc", {"preset": "p1", "tune": "ull", "rc": "cbr_ld_hq", "delay": "0", "profile": "high"}, 18_000_000),
        ("New Sunshine HEVC NVENC: High Bitrate", "hevc_nvenc", {"preset": "p1", "tune": "ull", "rc": "cbr_ld_hq", "delay": "0"}, 18_000_000)
    ]
    
    for label, codec_name, options, bitrate in test_configs:
        try:
            start_init = time.perf_counter()
            codec = av.CodecContext.create(codec_name, "w")
            codec.width = width
            codec.height = height
            codec.pix_fmt = "yuv420p"
            codec.framerate = 60
            codec.time_base = Fraction(1, 60)
            codec.bit_rate = bitrate
            codec.options = options
            codec.open()
            init_time = (time.perf_counter() - start_init) * 1000
            
            encode_times = []
            total_bytes = 0
            
            for arr in frames:
                vf = av.VideoFrame.from_ndarray(arr, format="rgb24")
                # Format to yuv420p
                t0 = time.perf_counter()
                vf_yuv = vf.reformat(
                    width=width,
                    height=height,
                    format="yuv420p",
                    dst_colorspace=Colorspace.ITU709,
                    dst_color_range=ColorRange.MPEG,
                    interpolation=Interpolation.BICUBIC
                )
                packets = codec.encode(vf_yuv)
                t1 = time.perf_counter()
                encode_times.append((t1 - t0) * 1000)
                for pkt in packets:
                    total_bytes += pkt.size
                    
            # Flush
            packets = codec.encode(None)
            for pkt in packets:
                total_bytes += pkt.size
                
            avg_ms = float(np.mean(encode_times))
            p95_ms = float(np.percentile(encode_times, 95))
            fps = 1000.0 / avg_ms if avg_ms > 0 else 0
            avg_bitrate_mbps = (total_bytes * 8) / (frames_count / 60.0) / 1_000_000
            
            results[codec_name] = {
                "label": label,
                "avg_encode_ms": round(avg_ms, 2),
                "p95_encode_ms": round(p95_ms, 2),
                "achieved_fps": round(fps, 1),
                "actual_bitrate_mbps": round(avg_bitrate_mbps, 2),
                "status": "PASS"
            }
            print(f"[{codec_name}] Avg Latency: {avg_ms:.2f} ms | P95: {p95_ms:.2f} ms | Throughput: {fps:.1f} FPS | Bitrate: {avg_bitrate_mbps:.2f} Mbps")
        except Exception as e:
            results[codec_name] = {"label": label, "error": str(e), "status": "FAIL"}
            print(f"[{codec_name}] Error: {e}")
            
    return results

def benchmark_color_pipeline():
    print("\n=== 2. Sunshine BT.709 vs Uncorrected BT.601 Color Matrix Accuracy ===")
    # Create reference test patterns: pure white, deep blacks, high saturation primary reds, greens, cyans
    ref_rgb = np.zeros((256, 256, 3), dtype=np.uint8)
    ref_rgb[0:64, :] = [255, 0, 0]      # Saturated Red
    ref_rgb[64:128, :] = [0, 255, 0]    # Saturated Green
    ref_rgb[128:192, :] = [16, 16, 16]  # Deep dark gray/black
    ref_rgb[192:256, :] = [240, 240, 240] # Near white
    
    vf = av.VideoFrame.from_ndarray(ref_rgb, format="rgb24")
    
    # 1. Uncorrected conversion (old behavior: default colorspace)
    vf_old_yuv = vf.reformat(format="yuv420p")
    vf_old_back = vf_old_yuv.reformat(format="rgb24")
    rgb_old = vf_old_back.to_ndarray()
    
    # 2. Sunshine BT.709 conversion (new behavior)
    vf_new_yuv = vf.reformat(
        format="yuv420p",
        dst_colorspace=Colorspace.ITU709,
        dst_color_range=ColorRange.MPEG,
        interpolation=Interpolation.BICUBIC
    )
    vf_new_back = vf_new_yuv.reformat(
        format="rgb24",
        src_colorspace=Colorspace.ITU709,
        src_color_range=ColorRange.MPEG,
        interpolation=Interpolation.BICUBIC
    )
    rgb_new = vf_new_back.to_ndarray()
    
    # Calculate Mean Squared Error & PSNR
    mse_old = np.mean((ref_rgb.astype(float) - rgb_old.astype(float)) ** 2)
    psnr_old = 10 * np.log10((255.0 ** 2) / (mse_old + 1e-10))
    
    mse_new = np.mean((ref_rgb.astype(float) - rgb_new.astype(float)) ** 2)
    psnr_new = 10 * np.log10((255.0 ** 2) / (mse_new + 1e-10))
    
    # Black level preservation check (reference is 16, 16, 16)
    black_old = np.mean(rgb_old[128:192, :])
    black_new = np.mean(rgb_new[128:192, :])
    
    print(f"Old Pipeline PSNR: {psnr_old:.2f} dB | Dark Level Drift: {abs(black_old - 16):.2f}")
    print(f"Sunshine BT.709 PSNR: {psnr_new:.2f} dB | Dark Level Drift: {abs(black_new - 16):.2f}")
    
    return {
        "old_psnr_db": round(psnr_old, 2),
        "new_psnr_db": round(psnr_new, 2),
        "psnr_improvement_db": round(psnr_new - psnr_old, 2),
        "old_dark_level_drift": round(float(abs(black_old - 16)), 2),
        "new_dark_level_drift": round(float(abs(black_new - 16)), 2)
    }

if __name__ == "__main__":
    enc_results = benchmark_encoders()
    color_results = benchmark_color_pipeline()
    out = {
        "encoder_benchmarks": enc_results,
        "color_benchmarks": color_results
    }
    with open("benchmark_screen_v2_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print("\nBenchmark successfully saved to benchmark_screen_v2_results.json")
