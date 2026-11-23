package com.example.mybatisplus.service;

import java.util.*;
import java.util.regex.Pattern;

/** Conservative grammar for autonomous spending; uncertain language stays on the manual path. */
public final class PurchaseGrounding {
    private PurchaseGrounding() {}
    private static final String PREFIX="^(?:请)?(?:帮我|给我|我想|我要|我想要)?(?:购买|下单|订购|买)\\s*";
    public static boolean requested(String message) {
        return Pattern.compile(PREFIX).matcher(message.trim()).find();
    }
    private static String chinese(int n) {
        String digits="零一二三四五六七八九";
        if (n<10) return digits.substring(n,n+1);
        return (n/10==1 ? "" : digits.substring(n/10,n/10+1))+"十"+(n%10==0 ? "" : digits.substring(n%10,n%10+1));
    }
    public static boolean exact(String message,List<Map<String,Object>> items) {
        String remaining=message.trim().replaceFirst(PREFIX, "");
        if (remaining.equals(message.trim()) || items.isEmpty()) return false;
        String units="(?:件|盒|瓶|袋|包|支|罐|份|个)";
        for (var item:items) {
            int qty=((Number)item.get("quantity")).intValue();
            String name=Pattern.quote((String)item.get("name"));
            String number="(?:"+qty+"|"+chinese(qty)+(qty==2 ? "|两" : "")+")";
            String pattern="(?<![0-9一二三四五六七八九十两])(?:"+number+"\\s*"+units+"\\s*(?:的\\s*)?"+name
                    +"|"+name+"\\s*"+number+"\\s*"+units+")(?![\\w\\u4e00-\\u9fff])";
            var matcher=Pattern.compile(pattern).matcher(remaining);
            if (!matcher.find()) return false;
            String next=matcher.replaceFirst("");
            if (next.contains((String)item.get("name"))) return false;
            remaining=next;
        }
        return remaining.replaceAll("[\\s，,。；;、和及与]+", "").isEmpty();
    }
}
