// Model poses enter the normal OpenVR driver API. No VRChat process hooks.
#include <winsock2.h>
#include <ws2tcpip.h>
#include <dxgi1_2.h>
#include <d3d11_1.h>
#include <wrl/client.h>
#include <openvr_driver.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstring>
#include <cstdio>
#include <memory>
#include <thread>

namespace {
using Clock = std::chrono::steady_clock;
#ifndef VIREA_DESKTOP_COMPOSITOR
#define VIREA_DESKTOP_COMPOSITOR 0
#endif
constexpr bool DesktopCompositor=VIREA_DESKTOP_COMPOSITOR!=0;
constexpr uint32_t PROTOCOL_VERSION=3; // explicit buttons and scroll axes
#pragma pack(push, 1)
struct PosePacket {
    char magic[4];
    uint32_t version;
    uint64_t session, sequence;
    double devices[3][7]; // xyz, xyzw in OpenVR standing space (metres)
    float hands[2][31][7]; // parent-relative xyz, xyzw
    uint32_t flags; // skeletons=1, left/right trigger=2/4, right system=8
    float scroll[2][2]; // left/right menu or action-menu axes
};
struct Ack {
    char magic[4] = {'V','G','A','1'};
    uint32_t version = PROTOCOL_VERSION;
    uint64_t session = 0, sequence = 0;
    uint32_t active = 0, skeleton = 0;
};
#pragma pack(pop)
static_assert(sizeof(PosePacket) == 1948);
static_assert(sizeof(Ack) == 32);

template<class T> bool validPose(const T* p, double positionLimit) {
    double norm = 0;
    for (int k=0;k<7;++k) if (!std::isfinite(p[k])) return false;
    for (int k=0;k<3;++k) if (std::abs(p[k]) > positionLimit) return false;
    for (int k=3;k<7;++k) norm += p[k]*p[k];
    return std::abs(norm - 1) < 0.02;
}
bool valid(const PosePacket& p) {
    if (std::memcmp(p.magic,"VGP1",4) || p.version != PROTOCOL_VERSION || (p.flags & ~0x3ffffu)) return false;
    for (const auto& axes:p.scroll) for (float axis:axes)
        if (!std::isfinite(axis) || std::abs(axis)>1) return false;
    for (const auto& d:p.devices) if (!validPose(d,20)) return false;
    if (p.flags & 1) for (const auto& h:p.hands)
        for (const auto& b:h) if (!validPose(b,1)) return false;
    return true;
}

class Display final : public vr::IVRDisplayComponent {
public:
    void GetWindowBounds(int32_t* x,int32_t* y,uint32_t* w,uint32_t* h) override {
        *x=0; *y=0; *w=960; *h=540;
    }
    // Valve's SimpleHMD sample lets SteamVR own a normal desktop swapchain.
    // This keeps pose/input devices independent of a shared-texture redirect.
    bool IsDisplayOnDesktop() override { return DesktopCompositor; }
    bool IsDisplayRealDisplay() override { return false; }
    void GetRecommendedRenderTargetSize(uint32_t* w,uint32_t* h) override { *w=960; *h=960; }
    void GetEyeOutputViewport(vr::EVREye eye,uint32_t* x,uint32_t* y,uint32_t* w,uint32_t* h) override {
        *x=eye==vr::Eye_Left?0:480; *y=0; *w=480; *h=540;
    }
    void GetProjectionRaw(vr::EVREye,float* l,float* r,float* t,float* b) override {
        *l=-1; *r=1; *t=-1; *b=1;
    }
    vr::DistortionCoordinates_t ComputeDistortion(vr::EVREye,float u,float v) override {
        vr::DistortionCoordinates_t c{};
        c.rfRed[0]=c.rfGreen[0]=c.rfBlue[0]=u;
        c.rfRed[1]=c.rfGreen[1]=c.rfBlue[1]=v;
        return c;
    }
    bool ComputeInverseDistortion(vr::HmdVector2_t*,vr::EVREye,uint32_t,float,float) override { return false; }
};

// Consume compositor frames without a physical display or desktop swapchain.
// The display redirect owns adapter selection (the HMD property alone does not
// select the compositor GPU in SteamVR's extended-desktop mode).
class VirtualDisplay final : public vr::ITrackedDeviceServerDriver, public vr::IVRVirtualDisplay {
    template<class T> using ComPtr=Microsoft::WRL::ComPtr<T>;
    struct TextureEntry {
        vr::SharedTextureHandle_t handle=0;
        ComPtr<ID3D11Texture2D> texture;
        ComPtr<IDXGIKeyedMutex> mutex;
        Clock::time_point retry{}, seen{};
        unsigned failures=0;
    };
    Clock::time_point epoch=Clock::now(), reported=epoch, nextOpen{};
    Microsoft::WRL::ComPtr<ID3D11Device> gpu;
    Microsoft::WRL::ComPtr<ID3D11Device1> gpu1;
    Microsoft::WRL::ComPtr<ID3D11DeviceContext> commands;
    ComPtr<ID3D11Texture2D> pixel;
    ComPtr<ID3D11Query> completion;
    std::array<TextureEntry,8> textures;
    DXGI_FORMAT pixelFormat=DXGI_FORMAT_UNKNOWN;
    uint64_t adapterLuid=0;
    bool pending=false, initialized=false, lost=false;
    uint64_t deviceInits=0, presents=0, opens=0, openFailures=0, retriesSkipped=0;
    uint64_t copies=0, completed=0, busy=0, mutexFailures=0, invalidFrames=0;
    HRESULT lastLegacy=S_OK, lastNt=S_OK;
    double maxPresentMs=0, maxWaitMs=0;

    void log(const char* line) {
        if(vr::VRDriverContext()) vr::VRDriverLog()->Log(line);
    }
    void report() {
        const auto now=Clock::now();
        if(now-reported<std::chrono::seconds(5)) return;
        char line[640];
        FormatDiagnostics(line,sizeof(line));
        log(line); reported=now;
    }
    bool pollCompletion() {
        if(!pending) return true;
        const auto result=commands->GetData(completion.Get(),nullptr,0,D3D11_ASYNC_GETDATA_DONOTFLUSH);
        if(result==S_FALSE) return false;
        pending=false;
        if(result==S_OK) { ++completed; return true; }
        // Recreating a removed device on the compositor render thread can stall
        // every frame. Keep the failure visible until the driver is reactivated.
        lost=true;
        log("VIREA display: GPU completion failed; driver reactivation required");
        return false;
    }
    TextureEntry* openTexture(vr::SharedTextureHandle_t handle) {
        const auto now=Clock::now();
        auto found=std::find_if(textures.begin(),textures.end(),[handle](const auto& x){return x.handle==handle;});
        if(found==textures.end()) {
            found=std::min_element(textures.begin(),textures.end(),[](const auto& a,const auto& b){return a.seen<b.seen;});
            *found={}; found->handle=handle;
        }
        auto& entry=*found; entry.seen=now;
        if(entry.texture) return &entry;
        if(now<entry.retry || now<nextOpen) { ++retriesSkipped; return nullptr; }
        ++opens;
        const auto nativeHandle=reinterpret_cast<HANDLE>(static_cast<uintptr_t>(handle));
        // These are distinct documented handle types. Never reinterpret an
        // opaque OpenVR handle as a COM pointer, nor close a borrowed handle.
        lastLegacy=gpu->OpenSharedResource(nativeHandle,IID_PPV_ARGS(&entry.texture));
        lastNt=E_NOINTERFACE;
        if(FAILED(lastLegacy) && gpu1)
            lastNt=gpu1->OpenSharedResource1(nativeHandle,IID_PPV_ARGS(&entry.texture));
        if(!entry.texture) {
            ++openFailures;
            entry.retry=now+std::chrono::seconds(1u<<std::min(entry.failures++,3u));
            nextOpen=now+std::chrono::milliseconds(100);
            if(openFailures<=3) {
                DWORD flags=0; SetLastError(0);
                const bool ntHandle=GetHandleInformation(nativeHandle,&flags)!=FALSE;
                const auto handleError=ntHandle?ERROR_SUCCESS:GetLastError();
                char line[320];
                std::snprintf(line,sizeof(line),"VIREA display: shared handle=%llu legacy=0x%08lx nt=0x%08lx nt_handle=%u handle_error=%lu (cached failure)",handle,lastLegacy,lastNt,unsigned(ntHandle),handleError);
                log(line);
            }
            return nullptr;
        }
        entry.texture.As(&entry.mutex);
        D3D11_TEXTURE2D_DESC desc{}; entry.texture->GetDesc(&desc);
        char line[256];
        std::snprintf(line,sizeof(line),"VIREA display: opened %ux%u format=%u samples=%u shared=%u using=%s",desc.Width,desc.Height,unsigned(desc.Format),desc.SampleDesc.Count,desc.MiscFlags,SUCCEEDED(lastLegacy)?"legacy":"NT");
        log(line);
        return &entry;
    }
public:
    bool Initialize(int selected) {
        if(initialized) return gpu!=nullptr && !lost;
        initialized=true; ++deviceInits;
        ComPtr<IDXGIFactory1> factory;
        ComPtr<IDXGIAdapter1> adapter;
        if(FAILED(CreateDXGIFactory1(IID_PPV_ARGS(&factory)))) return false;
        // A configured adapter must match the display redirect's LUID. Auto
        // uses DXGI's default adapter once; it does not probe every GPU per frame.
        if(FAILED(factory->EnumAdapters1(selected<0?0:UINT(selected),&adapter))) return false;
        const auto result=D3D11CreateDevice(adapter.Get(),D3D_DRIVER_TYPE_UNKNOWN,nullptr,
            D3D11_CREATE_DEVICE_BGRA_SUPPORT,nullptr,0,D3D11_SDK_VERSION,&gpu,nullptr,&commands);
        if(FAILED(result)) return false;
        gpu.As(&gpu1);
        D3D11_QUERY_DESC query{D3D11_QUERY_EVENT,0};
        if(FAILED(gpu->CreateQuery(&query,&completion))) { Deactivate(); return false; }
        DXGI_ADAPTER_DESC1 desc{}; adapter->GetDesc1(&desc);
        adapterLuid=(uint64_t(uint32_t(desc.AdapterLuid.HighPart))<<32)|desc.AdapterLuid.LowPart;
        char line[256];
        std::snprintf(line,sizeof(line),"VIREA display: initialized adapter=%d LUID=%08lx:%08lx device_inits=%llu",selected<0?0:selected,desc.AdapterLuid.HighPart,desc.AdapterLuid.LowPart,deviceInits);
        log(line); epoch=reported=Clock::now();
        return true;
    }
    vr::EVRInitError Activate(uint32_t id) override {
        auto properties=vr::VRProperties();
        const auto container=properties->TrackedDeviceToPropertyContainer(id);
        properties->SetStringProperty(container,vr::Prop_ModelNumber_String,"VIREA Virtual Display");
        const int selected=vr::VRSettings()->GetInt32("virea_pose","graphicsAdapterIndex");
        if(!Initialize(selected)) return vr::VRInitError_Driver_Failed;
        // Also publish the actual auto-selected adapter, so the compositor and
        // driver cannot independently choose different GPUs on hybrid systems.
        properties->SetUint64Property(container,vr::Prop_GraphicsAdapterLuid_Uint64,adapterLuid);
        return vr::VRInitError_None;
    }
    void Deactivate() override {
        textures={}; pixel.Reset(); completion.Reset(); commands.Reset(); gpu1.Reset(); gpu.Reset();
        pixelFormat=DXGI_FORMAT_UNKNOWN; pending=false; initialized=false; lost=false; nextOpen={};
    }
    void EnterStandby() override {}
    void* GetComponent(const char* name) override {
        return !std::strcmp(name,vr::IVRVirtualDisplay_Version)?static_cast<vr::IVRVirtualDisplay*>(this):nullptr;
    }
    void DebugRequest(const char*,char* output,uint32_t size) override { if(size) output[0]=0; }
    // Render-thread diagnostics only; the host DebugRequest can be concurrent.
    void FormatDiagnostics(char* output,uint32_t size) {
        if(size) std::snprintf(output,size,"VIREA display: elapsed=%.3f device_inits=%llu presents=%llu opens=%llu open_failures=%llu retry_skips=%llu copies=%llu completed=%llu busy=%llu mutex_failures=%llu invalid=%llu lost=%u max_present_ms=%.3f max_wait_ms=%.3f",
            std::chrono::duration<double>(Clock::now()-epoch).count(),deviceInits,presents,opens,openFailures,retriesSkipped,copies,completed,busy,mutexFailures,invalidFrames,unsigned(lost),maxPresentMs,maxWaitMs);
    }
    vr::DriverPose_t GetPose() override { return {}; }
    void Present(const vr::PresentInfo_t* info,uint32_t size) override {
        const auto started=Clock::now();
        struct Sample {
            Clock::time_point start; double& maximum;
            ~Sample(){maximum=std::max(maximum,std::chrono::duration<double,std::milli>(Clock::now()-start).count());}
        } sample{started,maxPresentMs};
        ++presents;
        if(!info || size<sizeof(*info) || !info->backbufferTextureHandle) { ++invalidFrames; return; }
        if(!gpu || lost) return;
        if(!pollCompletion()) { ++busy; return; }
        auto entry=openTexture(info->backbufferTextureHandle);
        if(!entry) return;
        D3D11_TEXTURE2D_DESC sourceDesc{}; entry->texture->GetDesc(&sourceDesc);
        if(!sourceDesc.Width || !sourceDesc.Height || sourceDesc.SampleDesc.Count!=1) { ++invalidFrames; return; }
        if(!pixel || pixelFormat!=sourceDesc.Format) {
            pixel.Reset(); pixelFormat=DXGI_FORMAT_UNKNOWN;
            D3D11_TEXTURE2D_DESC desc{};
            desc.Width=desc.Height=desc.ArraySize=desc.MipLevels=1;
            desc.Format=sourceDesc.Format; desc.SampleDesc.Count=1;
            desc.Usage=D3D11_USAGE_DEFAULT;
            if(FAILED(gpu->CreateTexture2D(&desc,nullptr,&pixel))) { ++invalidFrames; return; }
            pixelFormat=desc.Format;
        }
        // Present only queues GPU work. A busy producer never blocks the render
        // thread, and the completion query never reads pixels back to the CPU.
        if(entry->mutex && entry->mutex->AcquireSync(0,0)!=S_OK) { ++mutexFailures; return; }
        const D3D11_BOX box{0,0,0,1,1,1};
        commands->CopySubresourceRegion(pixel.Get(),0,0,0,0,entry->texture.Get(),0,&box);
        commands->End(completion.Get());
        commands->Flush();
        if(entry->mutex) entry->mutex->ReleaseSync(0);
        pending=true; ++copies;
    }
    void WaitForPresent() override {
        const auto started=Clock::now();
        const auto seconds=std::chrono::duration<double>(started-epoch).count();
        const auto next=std::chrono::duration<double>((std::floor(seconds*60)+1)/60);
        const auto deadline=epoch+std::chrono::duration_cast<Clock::duration>(next);
        while(pending && Clock::now()<deadline) {
            if(pollCompletion()) break;
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        // The virtual display clock advances even when a frame is late/missing.
        // Keeping a query pending prevents overwriting in-flight GPU work.
        std::this_thread::sleep_until(deadline);
        maxWaitMs=std::max(maxWaitMs,std::chrono::duration<double,std::milli>(Clock::now()-started).count());
        report();
    }
    bool GetTimeSinceLastVsync(float* seconds,uint64_t* counter) override {
        const auto elapsed=std::chrono::duration<double>(Clock::now()-epoch).count();
        *counter=static_cast<uint64_t>(elapsed*60); *seconds=static_cast<float>(elapsed-*counter/60.0); return true;
    }
};

class CompositorProvider final : public vr::IVRCompositorPluginProvider {
    VirtualDisplay display;
public:
    vr::EVRInitError Init(vr::IVRDriverContext* context) override {
        VR_INIT_COMPOSITOR_DRIVER_CONTEXT(context);
        return display.Initialize(vr::VRSettings()->GetInt32("virea_pose","graphicsAdapterIndex"))
            ?vr::VRInitError_None:vr::VRInitError_Driver_Failed;
    }
    void Cleanup() override { display.Deactivate(); VR_CLEANUP_COMPOSITOR_DRIVER_CONTEXT(); }
    const char* const* GetInterfaceVersions() override { return vr::k_InterfaceVersions; }
    void* GetComponent(const char* name) override { return display.GetComponent(name); }
};

class Device final : public vr::ITrackedDeviceServerDriver {
    int role;
    Display display;
    vr::DriverPose_t pose{};
    vr::VRInputComponentHandle_t skeleton=0, trigger=0, triggerValue=0, proximity=0, system=0;
    std::array<vr::VRInputComponentHandle_t,7> buttons{};
    std::array<vr::VRInputComponentHandle_t,2> scroll{};
public:
    uint32_t index=vr::k_unTrackedDeviceIndexInvalid;
    explicit Device(int deviceRole):role(deviceRole) {
        pose.qWorldFromDriverRotation.w=pose.qDriverFromHeadRotation.w=pose.qRotation.w=1;
        pose.vecPosition[1]=role==0?1.6:1.35;
        pose.vecPosition[0]=role==1?-0.6:role==2?0.6:0;
        pose.poseIsValid=pose.deviceIsConnected=true;
        pose.result=vr::TrackingResult_Running_OK;
    }
    vr::EVRInitError Activate(uint32_t id) override {
        index=vr::k_unTrackedDeviceIndexInvalid;
        auto p=vr::VRProperties();
        auto container=p->TrackedDeviceToPropertyContainer(id);
        // This is a generated virtual rig, not a measured Valve device. VRChat
        // consumes skeleton actions independently of controller identity.
        p->SetStringProperty(container,vr::Prop_ModelNumber_String,
            role==0?"VIREA Virtual HMD":"VIREA Generated Hand");
        p->SetStringProperty(container,vr::Prop_ManufacturerName_String,"VIREA");
        p->SetStringProperty(container,vr::Prop_TrackingSystemName_String,"virea_pose");
        p->SetStringProperty(container,vr::Prop_RegisteredDeviceType_String,
            role==0?"virea_pose/hmd":role==1?"virea_pose/left":"virea_pose/right");
        p->SetBoolProperty(container,vr::Prop_WillDriftInYaw_Bool,false);
        p->SetBoolProperty(container,vr::Prop_DeviceIsWireless_Bool,false);
        if (!role) {
            // Hybrid laptops may expose several adapters. A requested adapter
            // must be shared by SteamVR and the application; do not silently
            // fall back to another GPU after an invalid selection.
            const int adapterIndex=vr::VRSettings()->GetInt32("virea_pose","graphicsAdapterIndex");
            if(adapterIndex>=0) {
                IDXGIFactory1* factory=nullptr;
                if(FAILED(CreateDXGIFactory1(__uuidof(IDXGIFactory1),reinterpret_cast<void**>(&factory))))
                    return vr::VRInitError_Driver_Failed;
                IDXGIAdapter1* adapter=nullptr;
                const auto result=factory->EnumAdapters1(adapterIndex,&adapter);
                factory->Release();
                if(FAILED(result)) return vr::VRInitError_Driver_Failed;
                DXGI_ADAPTER_DESC1 desc{};
                const auto described=adapter->GetDesc1(&desc);
                adapter->Release();
                if(FAILED(described)) return vr::VRInitError_Driver_Failed;
                const uint64_t luid=(uint64_t(uint32_t(desc.AdapterLuid.HighPart))<<32)|desc.AdapterLuid.LowPart;
                p->SetUint64Property(container,vr::Prop_GraphicsAdapterLuid_Uint64,luid);
            }
            p->SetStringProperty(container,vr::Prop_RenderModelName_String,"generic_hmd");
            p->SetFloatProperty(container,vr::Prop_UserIpdMeters_Float,0.064f);
            p->SetFloatProperty(container,vr::Prop_DisplayFrequency_Float,60.f);
            p->SetFloatProperty(container,vr::Prop_SecondsFromVsyncToPhotons_Float,0.011f);
            p->SetFloatProperty(container,vr::Prop_UserHeadToEyeDepthMeters_Float,0.f);
            p->SetBoolProperty(container,vr::Prop_IsOnDesktop_Bool,false);
            p->SetBoolProperty(container,vr::Prop_DisplayDebugMode_Bool,DesktopCompositor);
            p->SetUint64Property(container,vr::Prop_CurrentUniverseId_Uint64,42);
            p->SetBoolProperty(container,vr::Prop_ContainsProximitySensor_Bool,true);
            if(vr::VRDriverInput()->CreateBooleanComponent(container,"/proximity",&proximity)!=vr::VRInputError_None)
                return vr::VRInitError_Driver_Failed;
            vr::VRDriverInput()->UpdateBooleanComponent(proximity,true,0);
        } else {
            p->SetInt32Property(container,vr::Prop_ControllerRoleHint_Int32,
                role==1?vr::TrackedControllerRole_LeftHand:vr::TrackedControllerRole_RightHand);
            p->SetStringProperty(container,vr::Prop_ControllerType_String,"virea_generated_hand");
            p->SetStringProperty(container,vr::Prop_RenderModelName_String,
                "{virea_pose}virea_generated_hand");
            p->SetStringProperty(container,vr::Prop_InputProfilePath_String,
                "{virea_pose}/input/virea_generated_hand_profile.json");
            auto input=vr::VRDriverInput();
            if(input->CreateBooleanComponent(container,"/input/system/click",&system)!=vr::VRInputError_None ||
               input->CreateBooleanComponent(container,"/input/trigger/click",&trigger)!=vr::VRInputError_None ||
               input->CreateScalarComponent(container,"/input/trigger/value",&triggerValue,
                   vr::VRScalarType_Absolute,vr::VRScalarUnits_NormalizedOneSided)!=vr::VRInputError_None)
                return vr::VRInitError_Driver_Failed;
            const char* paths[]={"/input/quick/click","/input/main/click","/input/action/click",
                "/input/back/click","/input/grip/click","/input/drop/click","/input/scroll/click"};
            for(int i=0;i<7;++i)
                if(input->CreateBooleanComponent(container,paths[i],&buttons[i])!=vr::VRInputError_None)
                    return vr::VRInitError_Driver_Failed;
            for(int i=0;i<2;++i)
                if(input->CreateScalarComponent(container,i?"/input/scroll/y":"/input/scroll/x",&scroll[i],
                    vr::VRScalarType_Absolute,vr::VRScalarUnits_NormalizedTwoSided)!=vr::VRInputError_None)
                    return vr::VRInitError_Driver_Failed;
            const auto result=input->CreateSkeletonComponent(container,
                role==1?"/input/skeleton/left":"/input/skeleton/right",
                role==1?"/skeleton/hand/left":"/skeleton/hand/right","/pose/raw",
                // Model estimates are not measured Full hand tracking. Full
                // enables VRChat's pinch inputs, which conflict with explicit
                // menu clicks. Both ranges still receive all 31 model bones.
                vr::VRSkeletalTracking_Estimated,nullptr,0,&skeleton);
            if(result!=vr::VRInputError_None) return vr::VRInitError_Driver_Failed;
        }
        index=id;
        return vr::VRInitError_None;
    }
    void Deactivate() override { index=vr::k_unTrackedDeviceIndexInvalid; }
    void EnterStandby() override {}
    void* GetComponent(const char* name) override {
        return role==0 && !std::strcmp(name,vr::IVRDisplayComponent_Version)?&display:nullptr;
    }
    void DebugRequest(const char*,char* response,uint32_t size) override { if(size) response[0]=0; }
    vr::DriverPose_t GetPose() override { return pose; }
    bool update(const PosePacket& packet,bool fresh) {
        const auto& p=packet.devices[role];
        std::copy(p,p+3,pose.vecPosition);
        pose.qRotation={p[6],p[3],p[4],p[5]};
        // A stationary virtual device stays tracked between inference jobs.
        // Hold the last received transforms; never synthesize an idle animation.
        // The packet watchdog still releases every trigger when input expires.
        pose.result=vr::TrackingResult_Running_OK;
        if(index==vr::k_unTrackedDeviceIndexInvalid) return false;
        vr::VRServerDriverHost()->TrackedDevicePoseUpdated(index,pose,sizeof(pose));
        if (!role) {
            vr::VRDriverInput()->UpdateBooleanComponent(proximity,true,0);
            return false;
        }
        auto input=vr::VRDriverInput();
        input->UpdateBooleanComponent(system,fresh && role==2 && (packet.flags&8),0);
        const bool press=fresh && (packet.flags & (1u << role));
        input->UpdateBooleanComponent(trigger,press,0);
        input->UpdateScalarComponent(triggerValue,press?1.f:0.f,0);
        for(int i=0;i<7;++i)
            input->UpdateBooleanComponent(buttons[i],fresh && (packet.flags&(1u<<(4+2*i+role-1))),0);
        for(int i=0;i<2;++i) input->UpdateScalarComponent(scroll[i],fresh?packet.scroll[role-1][i]:0.f,0);
        if (!(packet.flags&1) || !skeleton) return false;
        vr::VRBoneTransform_t bones[31]{};
        for(int b=0;b<31;++b) {
            auto& value=packet.hands[role-1][b];
            bones[b].position={{value[0],value[1],value[2],1}};
            bones[b].orientation={value[6],value[3],value[4],value[5]};
        }
        auto a=input->UpdateSkeletonComponent(skeleton,vr::VRSkeletalMotionRange_WithController,bones,31);
        auto b=input->UpdateSkeletonComponent(skeleton,vr::VRSkeletalMotionRange_WithoutController,bones,31);
        return a==vr::VRInputError_None && b==vr::VRInputError_None;
    }
};

class GeneratedPoseDriver final : public vr::IServerTrackedDeviceProvider {
    SOCKET socket_=INVALID_SOCKET;
    std::array<std::unique_ptr<Device>,3> devices;
    std::unique_ptr<VirtualDisplay> display;
    PosePacket current{};
    Clock::time_point received=Clock::now();
    bool hasPacket=false, winsock=false;
public:
    vr::EVRInitError Init(vr::IVRDriverContext* context) override {
        VR_INIT_SERVER_DRIVER_CONTEXT(context);
        WSADATA data;
        if(WSAStartup(MAKEWORD(2,2),&data)) return vr::VRInitError_Driver_Failed;
        winsock=true;
        socket_=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);
        sockaddr_in address{}; address.sin_family=AF_INET;
        address.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
        int port=vr::VRSettings()->GetInt32("virea_pose","port");
        if(port<1024 || port>65535) { Cleanup(); return vr::VRInitError_Driver_Failed; }
        address.sin_port=htons(static_cast<u_short>(port));
        if(socket_==INVALID_SOCKET || bind(socket_,reinterpret_cast<sockaddr*>(&address),sizeof(address))) {
            Cleanup(); return vr::VRInitError_Driver_Failed;
        }
        u_long nonblocking=1; ioctlsocket(socket_,FIONBIO,&nonblocking);
        const char* serials[]={"VIREA-HMD-1","VIREA-LEFT-1","VIREA-RIGHT-1"};
        for(int i=0;i<3;++i) {
            devices[i]=std::make_unique<Device>(i);
            current.devices[i][1]=i==0?1.6:1.35;
            current.devices[i][0]=i==1?-0.6:i==2?0.6:0;
            current.devices[i][6]=1;
            vr::VRServerDriverHost()->TrackedDeviceAdded(serials[i],i==0?vr::TrackedDeviceClass_HMD:vr::TrackedDeviceClass_Controller,devices[i].get());
        }
        if(!DesktopCompositor) {
            display=std::make_unique<VirtualDisplay>();
            vr::VRServerDriverHost()->TrackedDeviceAdded("VIREA-DISPLAY-1",vr::TrackedDeviceClass_DisplayRedirect,display.get());
        } else {
            vr::VRDriverLog()->Log("VIREA display: SteamVR desktop compositor; no virtual-display redirect");
        }
        vr::VRDriverLog()->Log("VIREA generated-pose driver ready on loopback; no emote synthesis");
        return vr::VRInitError_None;
    }
    void Cleanup() override {
        for(auto& device:devices) device.reset();
        display.reset();
        if(socket_!=INVALID_SOCKET) { closesocket(socket_); socket_=INVALID_SOCKET; }
        if(winsock) { WSACleanup(); winsock=false; }
        VR_CLEANUP_SERVER_DRIVER_CONTEXT();
    }
    const char* const* GetInterfaceVersions() override { return vr::k_InterfaceVersions; }
    bool ShouldBlockStandbyMode() override { return true; }
    void EnterStandby() override {}
    void LeaveStandby() override {}
    void RunFrame() override {
        sockaddr_in sender{}; int senderLength=sizeof(sender); bool acknowledge=false;
        for(int n=0;n<32;++n) {
            PosePacket incoming;
            int count=recvfrom(socket_,reinterpret_cast<char*>(&incoming),sizeof(incoming),0,
                reinterpret_cast<sockaddr*>(&sender),&senderLength);
            if(count==SOCKET_ERROR) break;
            if(count!=sizeof(incoming) || !valid(incoming) || sender.sin_addr.s_addr!=htonl(INADDR_LOOPBACK)) continue;
            if(hasPacket && incoming.session==current.session && incoming.sequence<=current.sequence) continue;
            current=incoming; hasPacket=true; received=Clock::now(); acknowledge=true;
        }
        const bool fresh=!hasPacket || Clock::now()-received<std::chrono::milliseconds(750);
        Ack ack; ack.session=current.session; ack.sequence=current.sequence;
        for(int i=0;i<3;++i) if(devices[i]) {
            if(devices[i]->update(current,fresh)) ack.skeleton|=1u<<i;
            if(devices[i]->index!=vr::k_unTrackedDeviceIndexInvalid) ack.active|=1u<<i;
        }
        if(acknowledge) sendto(socket_,reinterpret_cast<const char*>(&ack),sizeof(ack),0,
            reinterpret_cast<sockaddr*>(&sender),senderLength);
        vr::VREvent_t event{};
        while(vr::VRServerDriverHost()->PollNextEvent(&event,sizeof(event))) {}
    }
};
GeneratedPoseDriver driver;
CompositorProvider compositor;
}
extern "C" __declspec(dllexport) void* HmdDriverFactory(const char* name,int* error) {
    if(!std::strcmp(name,vr::IServerTrackedDeviceProvider_Version)) return &driver;
    if(!DesktopCompositor && !std::strcmp(name,vr::IVRCompositorPluginProvider_Version)) return &compositor;
    if(error) *error=vr::VRInitError_Init_InterfaceNotFound;
    return nullptr;
}
