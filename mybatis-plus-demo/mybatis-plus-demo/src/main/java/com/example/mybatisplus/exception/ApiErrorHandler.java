package com.example.mybatisplus.exception;

import java.util.Map;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.HandlerMethodValidationException;
import org.springframework.web.bind.MissingRequestHeaderException;

@RestControllerAdvice
public class ApiErrorHandler {
    @ExceptionHandler(PaymentException.class)
    public ResponseEntity<?> payment(PaymentException ex) {
        var response = ResponseEntity.status(ex.getStatus()).cacheControl(org.springframework.http.CacheControl.noStore());
        if (ex.getStatus().value() == 429) response.header("Retry-After", "900");
        return response.body(Map.of("code", ex.getCode(), "message", ex.getMessage(), "outcome", ex.getOutcome()));
    }
    @ExceptionHandler(ApiException.class)
    public ResponseEntity<?> business(ApiException ex) {
        return ResponseEntity.status(ex.getStatus())
                .body(Map.of("code", ex.getCode(), "message", ex.getMessage()));
    }

    @ExceptionHandler({MethodArgumentNotValidException.class, HttpMessageNotReadableException.class,
            HandlerMethodValidationException.class, MissingRequestHeaderException.class,
            org.springframework.web.method.annotation.MethodArgumentTypeMismatchException.class,
            org.springframework.web.bind.MissingServletRequestParameterException.class})
    public ResponseEntity<?> validation(Exception ex) {
        return ResponseEntity.badRequest()
                .body(Map.of("code", "VALIDATION_ERROR", "message", "请求参数不合法或缺少必填字段"));
    }

    @ExceptionHandler(DuplicateKeyException.class)
    public ResponseEntity<?> duplicate(DuplicateKeyException ex) {
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(Map.of("code", "CONFLICT", "message", "记录已存在，请勿重复提交"));
    }

    @ExceptionHandler(org.springframework.web.servlet.resource.NoResourceFoundException.class)
    public ResponseEntity<?> notFound(Exception ex) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(Map.of("code", "NOT_FOUND", "message", "接口不存在"));
    }

    @ExceptionHandler(org.springframework.web.HttpRequestMethodNotSupportedException.class)
    public ResponseEntity<?> methodNotAllowed(Exception ex) {
        return ResponseEntity.status(HttpStatus.METHOD_NOT_ALLOWED)
                .body(Map.of("code", "METHOD_NOT_ALLOWED", "message", "请求方法不支持"));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<?> unexpected(Exception ex) {
        // Do not expose SQL, credentials, or request bodies to clients.
        org.slf4j.LoggerFactory.getLogger(getClass()).error("Unhandled API error: {}",
                ex.getClass().getName());
        return ResponseEntity.internalServerError()
                .body(Map.of("code", "INTERNAL_ERROR", "message", "服务暂时不可用"));
    }
}
