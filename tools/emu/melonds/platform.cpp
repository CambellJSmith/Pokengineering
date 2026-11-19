#include "Platform.h"
#include <cstdio>
#include <cstdarg>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <chrono>
namespace melonDS { namespace Platform {
void SignalStop(StopReason, void*) {}
std::string GetLocalFilePath(const std::string& f) { return f; }
FileHandle* OpenFile(const std::string& path, FileMode mode) {
    const char* m = (mode & Write) ? ((mode & Preserve) ? "r+b" : "w+b") : "rb";
    if ((mode & Write) && (mode & Preserve)) { FILE* t = fopen(path.c_str(), "rb"); if (!t) { if (mode & NoCreate) return nullptr; m = "w+b"; } else fclose(t); }
    return (FileHandle*)fopen(path.c_str(), m);
}
FileHandle* OpenLocalFile(const std::string& p, FileMode m) { return OpenFile(p, m); }
bool FileExists(const std::string& n) { FILE* f = fopen(n.c_str(), "rb"); if (f) fclose(f); return f; }
bool LocalFileExists(const std::string& n) { return FileExists(n); }
bool CheckFileWritable(const std::string&) { return true; }
bool CheckLocalFileWritable(const std::string&) { return true; }
bool CloseFile(FileHandle* f) { return fclose((FILE*)f) == 0; }
bool IsEndOfFile(FileHandle* f) { return feof((FILE*)f); }
bool FileReadLine(char* s, int c, FileHandle* f) { return fgets(s, c, (FILE*)f); }
u64 FilePosition(FileHandle* f) { return ftell((FILE*)f); }
bool FileSeek(FileHandle* f, s64 o, FileSeekOrigin w) { return fseek((FILE*)f, o, w==FileSeekOrigin::Start?SEEK_SET:w==FileSeekOrigin::Current?SEEK_CUR:SEEK_END)==0; }
void FileRewind(FileHandle* f) { rewind((FILE*)f); }
u64 FileRead(void* d, u64 s, u64 c, FileHandle* f) { return fread(d, s, c, (FILE*)f); }
bool FileFlush(FileHandle* f) { return fflush((FILE*)f)==0; }
u64 FileWrite(const void* d, u64 s, u64 c, FileHandle* f) { return fwrite(d, s, c, (FILE*)f); }
u64 FileWriteFormatted(FileHandle* f, const char* fmt, ...) { va_list a; va_start(a, fmt); int r = vfprintf((FILE*)f, fmt, a); va_end(a); return r; }
u64 FileLength(FileHandle* f) { long p = ftell((FILE*)f); fseek((FILE*)f,0,SEEK_END); long l = ftell((FILE*)f); fseek((FILE*)f,p,SEEK_SET); return l; }
void Log(LogLevel lv, const char* fmt, ...) { if (lv < LogLevel::Warn) return; va_list a; va_start(a, fmt); vfprintf(stderr, fmt, a); va_end(a); }
struct Thread { std::thread t; };
Thread* Thread_Create(std::function<void()> fn) { auto* t = new Thread; t->t = std::thread(fn); return t; }
void Thread_Free(Thread* t) { if (t->t.joinable()) t->t.detach(); delete t; }
void Thread_Wait(Thread* t) { if (t->t.joinable()) t->t.join(); }
struct Semaphore { std::mutex m; std::condition_variable cv; int n = 0; };
Semaphore* Semaphore_Create() { return new Semaphore; }
void Semaphore_Free(Semaphore* s) { delete s; }
void Semaphore_Reset(Semaphore* s) { std::lock_guard<std::mutex> l(s->m); s->n = 0; }
void Semaphore_Wait(Semaphore* s) { std::unique_lock<std::mutex> l(s->m); s->cv.wait(l, [&]{ return s->n > 0; }); s->n--; }
bool Semaphore_TryWait(Semaphore* s, int ms) { std::unique_lock<std::mutex> l(s->m); if (!s->cv.wait_for(l, std::chrono::milliseconds(ms), [&]{ return s->n > 0; })) return false; s->n--; return true; }
void Semaphore_Post(Semaphore* s, int c) { { std::lock_guard<std::mutex> l(s->m); s->n += c; } s->cv.notify_all(); }
struct Mutex { std::mutex m; };
Mutex* Mutex_Create() { return new Mutex; }
void Mutex_Free(Mutex* m) { delete m; }
void Mutex_Lock(Mutex* m) { m->m.lock(); }
void Mutex_Unlock(Mutex* m) { m->m.unlock(); }
bool Mutex_TryLock(Mutex* m) { return m->m.try_lock(); }
void Sleep(u64 us) { std::this_thread::sleep_for(std::chrono::microseconds(us)); }
u64 GetMSCount() { return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(); }
u64 GetUSCount() { return std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(); }
void WriteNDSSave(const u8*, u32, u32, u32, void*) {}
void WriteGBASave(const u8*, u32, u32, u32, void*) {}
void WriteFirmware(const Firmware&, u32, u32, void*) {}
void WriteDateTime(int, int, int, int, int, int, void*) {}
void MP_Begin(void*) {} void MP_End(void*) {}
int MP_SendPacket(u8*, int, u64, void*) { return 0; }
int MP_RecvPacket(u8*, u64*, void*) { return 0; }
int MP_SendCmd(u8*, int, u64, void*) { return 0; }
int MP_SendReply(u8*, int, u64, u16, void*) { return 0; }
int MP_SendAck(u8*, int, u64, void*) { return 0; }
int MP_RecvHostPacket(u8*, u64*, void*) { return 0; }
u16 MP_RecvReplies(u8*, u64, u16, void*) { return 0; }
int Net_SendPacket(u8*, int, void*) { return 0; }
int Net_RecvPacket(u8*, void*) { return 0; }
void Camera_Start(int, void*) {} void Camera_Stop(int, void*) {}
void Camera_CaptureFrame(int, u32*, int, int, bool, void*) {}
void Mic_Start(void*) {} void Mic_Stop(void*) {}
int Mic_ReadInput(s16*, int, void*) { return 0; }
AACDecoder* AAC_Init() { return nullptr; }
void AAC_DeInit(AACDecoder*) {}
bool AAC_Configure(AACDecoder*, int, int) { return false; }
bool AAC_DecodeFrame(AACDecoder*, const void*, int, void*, int) { return false; }
bool Addon_KeyDown(KeyType, void*) { return false; }
void Addon_RumbleStart(u32, void*) {} void Addon_RumbleStop(void*) {}
float Addon_MotionQuery(MotionQueryType, void*) { return 0; }
DynamicLibrary* DynamicLibrary_Load(const char*) { return nullptr; }
void DynamicLibrary_Unload(DynamicLibrary*) {}
void* DynamicLibrary_LoadFunction(DynamicLibrary*, const char*) { return nullptr; }
}}
