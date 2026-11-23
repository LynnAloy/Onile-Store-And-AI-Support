package com.example.mybatisplus.controller;

import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.RequestMapping;

@Controller
public class HomeController {

    @RequestMapping("/")
    public String index() {
        // 转发到 static 目录下的 index.html
        return "forward:/index.html";
    }
}
