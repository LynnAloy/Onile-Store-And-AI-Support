package com.example.mybatisplus.controller;

import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/api/chat")
public class ChatController {

    // This describes routing only; FastAPI exposes its own /ai/health liveness endpoint.
    @GetMapping("/status")
    public Map<String, Object> getChatStatus() {
        return Map.of(
                "provider", "fastapi",
                "endpoint", "/ai/v1/conversations"
        );
    }
}
