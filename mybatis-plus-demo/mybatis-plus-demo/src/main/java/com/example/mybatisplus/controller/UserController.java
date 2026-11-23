package com.example.mybatisplus.controller;

import com.example.mybatisplus.dto.Requests;
import com.example.mybatisplus.security.CurrentUser;
import com.example.mybatisplus.service.UserService;
import jakarta.validation.Valid;
import java.util.Map;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/user")
public class UserController {
    private final UserService users;
    private final CurrentUser current;

    public UserController(UserService users, CurrentUser current) {
        this.users = users;
        this.current = current;
    }

    @GetMapping("/profile")
    public Map<String, Object> profile(@RequestParam(required = false) String userId) {
        return users.getUserProfile(current.username(userId));
    }

    @PutMapping("/profile")
    public void update(@Valid @RequestBody Requests.Profile request) {
        users.updateUserProfile(current.username(request.userId()), request);
    }

    @PutMapping("/profile/details")
    public Map<String, Object> updateDetails(@Valid @RequestBody Requests.ProfileDetails request) {
        return users.updateProfileDetails(current.username(request.basic().userId()), request);
    }
}
