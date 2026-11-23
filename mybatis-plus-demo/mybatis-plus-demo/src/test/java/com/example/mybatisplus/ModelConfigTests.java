package com.example.mybatisplus;
import com.example.mybatisplus.controller.ModelConfigController;
import com.example.mybatisplus.service.CommerceAccess;
import com.example.mybatisplus.security.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
class ModelConfigTests {
    @TempDir Path directory;
    @Test void savesAtomicallyAndRejectsStaleVersion() throws Exception {
        var access=mock(CommerceAccess.class); var current=mock(CurrentUser.class);
        when(current.actor()).thenReturn(new Actor("id","admin","USER","hash"));
        var controller=new ModelConfigController(access,current,new ObjectMapper(),directory.resolve("config.json").toString(),"old","http://127.0.0.1:11434");
        controller.put("Bearer token",new ModelConfigController.Config(0L,"new","http://127.0.0.1:11435/"));
        assertThat(Files.readString(directory.resolve("config.json"))).contains("new","11435","updatedBy");
        assertThatThrownBy(() -> controller.put("Bearer token",new ModelConfigController.Config(0L,"other","http://127.0.0.1:11434"))).hasMessageContaining("已变化");
        verify(access,atLeast(2)).requireAdmin(current.actor(),"token");
    }
    @Test void keyNeverReturnedAndOnlyPreservedForSameTarget() throws Exception {
        var access=mock(CommerceAccess.class); var current=mock(CurrentUser.class);
        when(current.actor()).thenReturn(new Actor("id","admin","USER","hash"));
        var controller=new ModelConfigController(access,current,new ObjectMapper(),directory.resolve("secret.json").toString(),"old","http://127.0.0.1:11434");
        var first=controller.put("Bearer token",new ModelConfigController.Config(0L,"model","https://api.example.com/v1","openai","synthetic-test-key",false));
        assertThat(first.getBody().toString()).doesNotContain("synthetic-test-key").contains("hasApiKey=true");
        controller.put("Bearer token",new ModelConfigController.Config(1L,"other","https://api.example.com/v1","openai",null,false));
        assertThat(Files.readString(directory.resolve("secret.json"))).contains("synthetic-test-key");
        controller.put("Bearer token",new ModelConfigController.Config(2L,"other","https://different.example.com/v1","openai",null,false));
        assertThat(Files.readString(directory.resolve("secret.json"))).doesNotContain("synthetic-test-key");
    }
    @Test void rejectsUnsafeEndpoints() {
        for (String value:java.util.List.of("file:///tmp/model","http://remote.example","https://user:secret@example.com","https://example.com/?key=secret"))
            assertThatThrownBy(() -> ModelConfigController.validateEndpoint(value)).isInstanceOf(RuntimeException.class);
        assertThat(ModelConfigController.validateEndpoint("http://127.0.0.1:11434/")).isEqualTo("http://127.0.0.1:11434");
    }
}
