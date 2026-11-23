package com.example.mybatisplus.security;

public record Actor(String id, String username, String scope, String sessionHash) {}
